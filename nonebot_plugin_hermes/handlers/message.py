"""
消息处理器

priority=1 perception:写 MessageBuffer + BotRegistry,非阻塞
priority=98 main:触发判断 → reactive 决策 → 出向
"""

from __future__ import annotations

import asyncio
import time
from typing import List, Optional

import nonebot_plugin_alconna as alconna
from nonebot import logger, on_message
from nonebot.adapters import Bot, Event
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from .. import mcp as _mcp  # lazy access to runtime singletons
from ..config import plugin_config
from ..core.hermes_client import hermes_client, maybe_extract_decision_reply_text
from ..core.message_buffer import BufferedMessage
from ..core.outbound import send_text_with_media
from ..core.prompt_builder import (
    build_passive_system_prompt,
    build_passive_user_content,
    build_reactive_system_prompt,
    build_reactive_user_content,
)
from ..core.session import session_manager
from ..utils import check_isolation, get_adapter_name


async def _ignore_rule(event: Event) -> bool:
    try:
        msg_text = event.get_plaintext().strip()
    except Exception:
        return False
    if not msg_text:
        return True
    for prefix in plugin_config.hermes_ignore_prefix:
        if msg_text.startswith(prefix):
            return False
    return True


receive_message = on_message(rule=Rule(_ignore_rule), priority=98, block=True)
perception_message = on_message(priority=1, block=False)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _is_bot_at(uni_msg: alconna.UniMessage, bot_self_id: str) -> bool:
    if uni_msg.has(alconna.At):
        for seg in uni_msg[alconna.At]:
            if str(seg.target) == str(bot_self_id):
                return True
    return False


def _msg_at_only_other_users(uni_msg: alconna.UniMessage, bot_self_id: str) -> bool:
    """消息含 At 段、且所有 At target 都不是 bot 自身 → True。

    用于 reactive 入口 C 层过滤(模式 1 修复):active 窗口内,若消息明确 @ 了
    其他用户但**未点名 bot**,视作非本路径触发,只让 perception matcher 写 buffer,
    不进 chat() 决策。无 At 段时返回 False(走原有路径)。
    """
    if not uni_msg.has(alconna.At):
        return False
    return not _is_bot_at(uni_msg, bot_self_id)


# 单条昵称在 prompt 里的最大字符数。
# 中文 12 字 / 英文 24 字符,覆盖正常昵称;超长名片(常被用来塞动作短语/
# 系统消息伪装)会被截断成「前缀…」,降低被 LLM 当系统信号读的风险。
_MAX_NICKNAME_LEN = 24


def _sanitize_nickname(value) -> Optional[str]:
    """清洗外部输入昵称,失败返 None。

    防御目标(顺手卫生 + 阻挡 [user=…] 定界符伪装):
    1. 控制字符 / 换行 / 零宽 → 全删,防止把多行片段塞进 prompt
    2. `]` 全角化,防止把 [user=…]: 标签提前闭合伪装成系统标签
    3. 长度 cap = _MAX_NICKNAME_LEN,超长截断 + 加省略号
    """
    if value is None:
        return None
    s = str(value)
    s = "".join(ch for ch in s if ch.isprintable())  # Cc/Cf/Cs 全过滤,ASCII space 保留
    s = s.replace("]", "］")  # 全角 `]`,与半角 `]` 视觉相近不破坏外观,但不闭合 [user=…] 标签
    s = s.strip()
    if not s:
        return None
    if len(s) > _MAX_NICKNAME_LEN:
        s = s[:_MAX_NICKNAME_LEN] + "…"
    return s


def _extract_sender_nickname(event: Event, adapter_name: str) -> Optional[str]:
    """从 event 抽真实昵称(群名片优先),失败回 None。所有命中字段都过 _sanitize_nickname。

    保持 cross-adapter,不 import adapter-specific 类型,全靠 getattr 链——
    各 adapter event 形状不一致,Python 重命名/缺失字段都吞掉。

    覆盖的形状:
    - OneBot v11/v12: event.sender.card(群名片) → event.sender.nickname
    - QQ Official / Kook 等 .author: event.author.{global_name,nickname,username,name}
    - Discord: event.member.nick(server 名片) → 同上 author 链兜底
    - Telegram: event.from_.first_name + last_name → username
    """
    sender = getattr(event, "sender", None)
    if sender is not None:
        n = _sanitize_nickname(getattr(sender, "card", None)) or _sanitize_nickname(getattr(sender, "nickname", None))
        if n:
            return n

    member = getattr(event, "member", None)
    if member is not None:
        n = _sanitize_nickname(getattr(member, "nick", None)) or _sanitize_nickname(getattr(member, "nickname", None))
        if n:
            return n

    author = getattr(event, "author", None)
    if author is not None:
        for attr in ("global_name", "nickname", "username", "name"):
            n = _sanitize_nickname(getattr(author, attr, None))
            if n:
                return n

    from_user = getattr(event, "from_", None) or getattr(event, "from_user", None)
    if from_user is not None:
        first = _sanitize_nickname(getattr(from_user, "first_name", None))
        last = _sanitize_nickname(getattr(from_user, "last_name", None))
        if first or last:
            # 合并后再过一次 sanitize,确保拼接结果也受长度上限约束
            return _sanitize_nickname(" ".join(p for p in (first, last) if p))
        n = _sanitize_nickname(getattr(from_user, "username", None))
        if n:
            return n

    return None


async def _extract_image_urls(uni_msg: alconna.UniMessage, bot: Bot, adapter_name: str) -> List[str]:
    """从 UniMessage 中抽出图片 URL 列表(可直接 HTTP GET 拿字节的那种)。

    多 adapter 行为不一致:
    - OneBot v11 / QQ Official / Discord 等:alconna 直接在 Image 段上填好 `.url`,
      最廉价路径,优先用
    - Telegram:alconna 只填 `.id`(就是 file_id),URL 必须二次调
      `bot.get_file(file_id)` 拿到 `file_path` 后拼成 `https://api.telegram.org/
      file/bot<TOKEN>/<file_path>`。这条路径 URL 里**带 token**,但 fetcher
      和 DB 都本地,落地可接受;且 file_path 只有 ~1h 有效,异步 fetcher 必须
      及时抓字节进 ImageCache,后面 MCP 工具读 cache 不再依赖 URL
    - 其他 adapter:只看 `.url`,没的话就放弃这张图(不抛、不 fail bot)

    本函数是 async 因为 telegram 分支要 await bot.get_file。
    """
    urls: List[str] = []
    if not uni_msg.has(alconna.Image):
        return urls
    adapter_lc = (adapter_name or "").lower()
    for img in uni_msg[alconna.Image]:
        url = getattr(img, "url", None)
        if url and isinstance(url, str) and url.startswith(("http://", "https://")):
            urls.append(url)
            continue
        file_id = getattr(img, "id", None)
        if not file_id:
            continue
        if "telegram" in adapter_lc:
            resolved = await _resolve_telegram_file_url(bot, file_id)
            if resolved:
                urls.append(resolved)
                continue
        # 其他 adapter 但 Image 没 .url 的情况:debug 一行,不当错误处理
        logger.debug(
            f"[image] skipped image segment with no resolvable URL (adapter={adapter_lc} id={file_id[:24]}...)"
        )
    return urls


# Telegram `bot.get_file(file_id)` → URL 短期缓存。
# 同一事件经过 priority=1 perception + priority=98 main handler 两个 matcher,
# 各自跑一次 _extract_image_urls,如果不缓存就要打两次 Telegram API
# (~300-500ms 网络往返/次)。
#
# TTL 设 60 秒:Telegram 自己返的 file_path 大约 1 小时有效,我们 60s 内
# 复用足够覆盖事件突发,且远小于真实失效窗口,不引入隐患。
_RESOLVED_URL_TTL_S = 60.0
_resolved_url_cache: dict[tuple[str, str], tuple[str, float]] = {}


async def _resolve_telegram_file_url(bot: Bot, file_id: str) -> Optional[str]:
    """Telegram file_id → 可拉的 HTTPS URL。失败返 None,perception 不崩。

    URL 里含 token,只在 plugin 本地 DB / fetcher 流转(不会进 prompt / MCP 返回)。
    file_path 一般 ~1h 失效,fetcher 必须及时抓——本设计走 perception 异步触发,
    秒级到达 fetcher,不会拖到失效。

    短期缓存:同一 (bot_self_id, file_id) 60s 内复用上次 resolve 结果,避免
    perception + main handler 两层各调一次 Telegram getFile API。
    """
    cache_key = (str(getattr(bot, "self_id", "?")), file_id)
    now = time.monotonic()
    cached = _resolved_url_cache.get(cache_key)
    if cached and cached[1] > now:
        return cached[0]
    try:
        file = await bot.get_file(file_id=file_id)
    except Exception as exc:
        logger.warning(f"[image] telegram get_file failed for file_id={file_id[:24]}...: {exc}")
        return None
    file_path = getattr(file, "file_path", None)
    token = getattr(getattr(bot, "bot_config", None), "token", None)
    if not file_path or not token:
        logger.warning(f"[image] telegram get_file returned no file_path/token (file_id={file_id[:24]}...)")
        return None
    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    _resolved_url_cache[cache_key] = (url, now + _RESOLVED_URL_TTL_S)
    # 偶尔顺手清掉过期 entry,避免长期跑爆字典(O(N) 但 N 很小)
    if len(_resolved_url_cache) > 256:
        expired = [k for k, (_u, exp) in _resolved_url_cache.items() if exp <= now]
        for k in expired:
            _resolved_url_cache.pop(k, None)
    return url


@perception_message.handle()
async def handle_perception(bot: Bot, event: Event):
    """记录消息到 MessageBuffer + 维护 BotRegistry。"""
    if _mcp.message_buffer is None or _mcp.bot_registry is None:
        return

    try:
        target = alconna.get_target()
        adapter_name = get_adapter_name(target)
        user_id = event.get_user_id()
    except Exception:
        return

    if user_id == str(bot.self_id):
        return

    try:
        uni_msg = alconna.UniMessage.generate_without_reply(event=event, bot=bot)
    except Exception:
        return

    msg_text = uni_msg.extract_plain_text().strip()
    image_urls = await _extract_image_urls(uni_msg, bot, adapter_name)
    nickname = _extract_sender_nickname(event, adapter_name) or user_id

    # 文本太长截断
    max_len = plugin_config.hermes_perception_text_length
    if msg_text and len(msg_text) > max_len:
        msg_text = msg_text[:max_len] + "..."

    if image_urls and plugin_config.hermes_perception_image_mode != "none":
        placeholder = " [图片]"
        msg_text = (msg_text + placeholder) if msg_text else placeholder.strip()

    if not msg_text and not image_urls:
        return

    now = _now_ms()
    group_id = None if target.private else target.id

    # 写 MessageBuffer
    if plugin_config.hermes_perception_enabled or plugin_config.hermes_active_session_enabled:
        _mcp.message_buffer.append(
            BufferedMessage(
                ts=now,
                adapter=adapter_name,
                group_id=group_id,
                user_id=user_id,
                nickname=nickname,
                content=msg_text,
                image_urls=image_urls,
                is_bot=False,
            )
        )

    # 写 BotRegistry
    scope = "private" if target.private else "group"
    scope_id = user_id if target.private else (group_id or "")
    if scope_id:
        _mcp.bot_registry.upsert(
            adapter=adapter_name,
            scope=scope,
            scope_id=scope_id,
            bot_self_id=str(bot.self_id),
            target=target,
            ts=now,
        )

    logger.debug(
        f"[HERMES perception] {adapter_name}/{scope}/{scope_id} user={user_id} "
        f"text_len={len(msg_text)} imgs={len(image_urls)}"
    )


@receive_message.handle()
async def handle_message(bot: Bot, event: Event, matcher: Matcher):
    if _mcp.message_buffer is None or _mcp.active_sessions is None:
        return

    try:
        target = alconna.get_target()
    except Exception:
        matcher.skip()

    adapter_name = get_adapter_name(target)
    user_id = event.get_user_id() or "user"
    if user_id == str(bot.self_id):
        matcher.skip()

    if not check_isolation(event, target):
        logger.debug(
            f"[HERMES skip] isolation_denied adapter={get_adapter_name(target)} "
            f"target={target.id} private={target.private} user={user_id}"
        )
        matcher.skip()

    # 引用消息提取
    replied_text = ""
    replied_image_urls: List[str] = []
    if hasattr(event, "reply") and event.reply:
        try:
            replied_message = await alconna.UniMessage.generate(message=event.reply.message, bot=bot)
            replied_text = replied_message.extract_plain_text().strip()
            replied_image_urls = await _extract_image_urls(replied_message, bot, adapter_name)
            if replied_image_urls and not replied_text:
                replied_text = "[图片]"
        except Exception as e:
            logger.warning(f"[HERMES] 提取引用消息失败: {e}")

    try:
        uni_msg = alconna.UniMessage.generate_without_reply(event=event, bot=bot)
    except Exception:
        matcher.skip()

    msg_text = uni_msg.extract_plain_text().strip()
    if replied_text:
        msg_text = f"(引用: {replied_text}) {msg_text}".strip()

    image_urls = await _extract_image_urls(uni_msg, bot, adapter_name)
    image_urls.extend(replied_image_urls)
    nickname = _extract_sender_nickname(event, adapter_name) or user_id

    logger.debug(
        f"[HERMES recv] adapter={adapter_name} target={target.id} private={target.private} "
        f"user={user_id} nick={nickname!r} is_tome={event.is_tome()} self_id={bot.self_id!r} "
        f"at_targets={[str(s.target) for s in uni_msg[alconna.At]] if uni_msg.has(alconna.At) else []} "
        f"text_len={len(msg_text)} imgs={len(image_urls)}"
    )

    if not msg_text and not image_urls:
        logger.debug(f"[HERMES skip] empty adapter={adapter_name} user={user_id}")
        matcher.skip()

    group_id = None if target.private else target.id
    now = _now_ms()

    # --- 触发判断 ---
    is_explicit_trigger = False
    if target.private:
        is_explicit_trigger = True
    else:
        is_mentioned = event.is_tome() or _is_bot_at(uni_msg, str(bot.self_id))
        trigger_mode = plugin_config.hermes_group_trigger
        if trigger_mode == "at":
            is_explicit_trigger = is_mentioned
        elif trigger_mode == "all":
            is_explicit_trigger = True
        elif trigger_mode == "keyword":
            for kw in plugin_config.hermes_keywords:
                if msg_text.startswith(kw):
                    msg_text = msg_text[len(kw) :].strip()
                    is_explicit_trigger = True
                    break
            if not is_explicit_trigger and is_mentioned:
                is_explicit_trigger = True

    # --- M1 核心:活跃态分支 ---
    in_active_window = (
        not target.private
        and plugin_config.hermes_active_session_enabled
        and group_id is not None
        and _mcp.active_sessions.is_active(adapter_name, group_id, now)
    )

    if not is_explicit_trigger and not in_active_window:
        logger.debug(f"[HERMES skip] not_active_not_explicit adapter={adapter_name} group={group_id} user={user_id}")
        matcher.skip()

    # C: 活跃窗口内,若消息只 @ 他人未点名 bot,视作非本路径触发,只让 perception
    # 写 buffer,不进 chat() 决策。修「跨目标 @ 误抢」模式 1。
    # 显式触发(at-bot)早已在上面计入 is_explicit_trigger,不会到这里被过滤。
    if in_active_window and not is_explicit_trigger and _msg_at_only_other_users(uni_msg, str(bot.self_id)):
        logger.debug(
            f"[HERMES reactive] skip: msg @s only other users (adapter={adapter_name} group={group_id} user={user_id})"
        )
        matcher.skip()

    # 显式触发:进入 / 续期活跃态(群聊场景)
    if is_explicit_trigger and not target.private and group_id and plugin_config.hermes_active_session_enabled:
        _mcp.active_sessions.trigger(adapter_name, group_id, user_id, now_ms=now)
        logger.info(f"[HERMES] active_session triggered/renewed: {adapter_name}/{group_id} by {user_id}")

    if not target.private:
        logger.info(
            f"[HERMES] dispatch: group={group_id} explicit={is_explicit_trigger} "
            f"in_active={in_active_window} mode="
            f"{'reactive' if plugin_config.hermes_active_session_enabled else 'passive'}"
        )

    # --- 调用 Hermes ---
    if target.private or not plugin_config.hermes_active_session_enabled:
        # 原 v0.1.6 等价路径:passive 模式,raw_text 直接当回复
        await _handle_passive_path(
            bot=bot,
            target=target,
            adapter_name=adapter_name,
            user_id=user_id,
            nickname=nickname,
            group_id=group_id,
            text=msg_text,
            image_urls=image_urls,
            is_private=target.private,
            now_ms=now,
        )
        return

    # 群聊 + 活跃态启用 → reactive 决策
    await _handle_reactive_path(
        bot=bot,
        target=target,
        adapter_name=adapter_name,
        user_id=user_id,
        nickname=nickname,
        group_id=group_id,
        text=msg_text,
        image_urls=image_urls,
        is_explicit_trigger=is_explicit_trigger,
        now_ms=now,
    )


async def _run_passive_turn(
    *,
    bot: Bot,
    target,
    adapter_name: str,
    user_id: str,
    group_id: Optional[str],
    text: str,
    image_urls: List[str],
    is_private: bool,
    now_ms: int,
):
    """跑一发 passive turn,返回 ChatResult 或 None(被 submit_decision 静默兜底等情况)。"""
    session_key = session_manager.get_session_key(
        adapter_name=adapter_name,
        is_private=is_private,
        user_id=user_id,
        group_id=group_id,
    )

    # 群聊 + 默认配置(active_session=false)+ perception_enabled:补回 0.1.6
    # 「@bot 时让 LLM 看到群里旁观历史」。before_ts=now_ms 排除 perception 在
    # 同一事件 priority=1 时刚写入的当前消息,避免历史里出现重复。
    # 私聊不注入(0.1.6 起 perception 在私聊就是 no-op,Hermes session 已覆盖)。
    # 历史从 0.2.x 起放进 user content 而非 system,以维持 system 字节稳定。
    recent: List[BufferedMessage] = []
    if not is_private and group_id and plugin_config.hermes_perception_enabled and _mcp.message_buffer is not None:
        recent = list(
            _mcp.message_buffer.get_recent(
                adapter=adapter_name,
                group_id=group_id,
                limit=plugin_config.hermes_perception_buffer,
                before_ts=now_ms,
            )
        )

    system_prompt = build_passive_system_prompt(
        adapter=adapter_name,
        is_private=is_private,
        user_id=user_id,
        group_id=group_id,
    )
    user_content = build_passive_user_content(
        recent_messages=recent,
        current_text=text or " ",
        current_image_urls=image_urls,
    )

    result = await hermes_client.chat(
        text="",
        image_urls=[],
        session_key=session_key,
        user_id=user_id,
        group_id=group_id,
        adapter_name=adapter_name,
        is_private=is_private,
        mode="passive",
        expect_structured=False,
        system_prompt=system_prompt,
        user_content_override=user_content,
    )

    # 上游 transport_error 同款保护(见 _run_reactive_turn 同名分支注释)。
    # passive 路径下私聊总是显式对话,群聊已通过触发判断进得来,两边都该有可见反馈;
    # 配空 fallback_text 时静默,保留逃生口。
    if result.is_transport_error:
        fallback_text = plugin_config.hermes_transport_error_fallback_text
        logger.warning(
            f"[HERMES passive] transport error fallback "
            f"(group={group_id}, is_private={is_private}, "
            f"fallback={'silent' if not fallback_text else 'friendly_text'}); "
            f"upstream raw_text suppressed (len={len(result.raw_text or '')})"
        )
        if fallback_text:
            await send_text_with_media(
                bot=bot,
                target=target,
                text=fallback_text,
                media_urls=[],
                at_user_id=None if is_private else user_id,
            )
        return result

    # 防御:同一 Hermes session 之前跑过 reactive 时学到 submit_decision 契约,
    # 切回 passive 后仍可能吐 JSON。检测并抠 reply_text;不命中则用原 raw_text。
    reply_text = result.raw_text
    extracted = maybe_extract_decision_reply_text(reply_text)
    if extracted is not None:
        if extracted == "":
            logger.info(f"[HERMES passive] LLM 返回 should_reply=false 结构,静默(group={group_id})")
            return result
        logger.warning(f"[HERMES passive] 检测到 submit_decision 形 JSON 残留,抠 reply_text 后发送(group={group_id})")
        reply_text = extracted

    if not reply_text and not result.media_urls:
        return result
    await send_text_with_media(
        bot=bot,
        target=target,
        text=reply_text,
        media_urls=result.media_urls,
        at_user_id=None if is_private else user_id,
    )
    return result


async def _run_reactive_turn(
    *,
    bot: Bot,
    target,
    adapter_name: str,
    user_id: str,
    group_id: str,
    text: str,
    image_urls: List[str],
    is_explicit_trigger: bool,
    now_ms: int,
    nickname: Optional[str] = None,
):
    """跑一发 reactive turn,返回 hermes_client.chat() 的 ChatResult,或 None 表示提前 return。

    外壳 _handle_reactive_path 负责 inflight + 图片门控,这里只管:
    拉 recent → 组 prompt → 调 chat → 解析 decision → 发出向 → 回写 buffer。
    """
    assert _mcp.message_buffer is not None and _mcp.active_sessions is not None

    # 用 get_if_active 而非 get():get() 是 debug-only 裸访问,可能返回已过期 session;
    # get_if_active 与 is_active(handle_message 入口处用过)同口径。
    session = _mcp.active_sessions.get_if_active(adapter_name, group_id, now_ms)
    if session is None:
        return None  # 防御:窗口刚刚过期 / 被外部 end()

    # B.3: 快照本 turn 入口时的 last_bot_reply_at,供 chat() 返回后判定 agent loop
    # 期间是否有外部(MCP push_message)推过 bot 自己的回复。若发生,即使 LLM 返
    # should_reply=True 也必须抑制本路 send,否则同 turn 内双答。
    # 2026-05-18 17:48 事件原型:Hermes 在 reactive agent loop 内既调 push_message
    # 又在 submit_decision 里把同样答案再吐了一遍,plugin 接下来都发了一遍 → 双答。
    last_bot_reply_at_at_entry = session.last_bot_reply_at

    recent = _mcp.message_buffer.get_recent(
        adapter=adapter_name,
        group_id=group_id,
        limit=plugin_config.hermes_perception_buffer,
    )

    system_prompt = build_reactive_system_prompt()
    user_content = build_reactive_user_content(
        adapter=adapter_name,
        group_id=group_id,
        triggered_by=session.triggered_by,
        triggered_by_nickname=None,
        topic_hint=session.topic_hint,
        recent_messages=recent,
        current_user_id=user_id,
        current_nickname=nickname or user_id,
        current_text=text or "[图片]",
        current_image_urls=image_urls,
    )

    session_key = session_manager.get_session_key(
        adapter_name=adapter_name,
        is_private=False,
        user_id=user_id,
        group_id=group_id,
    )
    # 注:user_content_override 已携带 user message 的全部内容(text + 多模态);
    # text/image_urls 在 chat() 中会被忽略(见 hermes_client.chat 文档),此处显式传 ""
    # /[] 让契约清晰,避免被读者误以为 image_urls 也参与了构造。
    result = await hermes_client.chat(
        text="",
        image_urls=[],
        session_key=session_key,
        user_id=user_id,
        group_id=group_id,
        adapter_name=adapter_name,
        is_private=False,
        mode="reactive",
        expect_structured=True,
        structured_tool_name="submit_decision",
        system_prompt=system_prompt,
        user_content_override=user_content,
    )

    if result.parse_failed or result.structured is None:
        # 上游 transport_error(5xx / 网络断 / 流被掐):raw_text 是服务端错误信息原文
        # (如 "Model generated invalid tool call: ..."),原文转发会把内部错误丢到群里
        # 既泄密又难看。换成 config 里的友好兜底文本;空串则静默。
        # parse_failed 但非 transport(LLM 真的回了点啥但结构错):原样转发 raw_text,
        # 仍可能是用户想要的回答。
        if result.is_transport_error and is_explicit_trigger:
            fallback_text = plugin_config.hermes_transport_error_fallback_text
            logger.warning(
                f"[HERMES reactive] transport error fallback "
                f"(group={group_id}, fallback={'silent' if not fallback_text else 'friendly_text'}); "
                f"upstream raw_text suppressed (len={len(result.raw_text or '')})"
            )
            if fallback_text:
                await send_text_with_media(
                    bot=bot,
                    target=target,
                    text=fallback_text,
                    media_urls=[],
                    at_user_id=user_id,
                )
            return result

        logger.warning(
            f"[HERMES reactive] structured parse failed (group={group_id}, "
            f"transport_error={result.is_transport_error}); fallback="
            f"{'raw_text' if is_explicit_trigger and result.raw_text else 'silent'}"
        )
        # 静默兜底:显式触发时降级发 raw_text;非显式触发(被动)时静默
        if is_explicit_trigger and result.raw_text:
            await send_text_with_media(
                bot=bot,
                target=target,
                text=result.raw_text,
                media_urls=result.media_urls,
                at_user_id=user_id,
            )
        return result

    logger.info(
        f"[HERMES reactive] decision adapter={adapter_name} group={group_id} user={user_id} "
        f"explicit={is_explicit_trigger} should_reply={result.structured.get('should_reply')} "
        f"should_exit_active={result.structured.get('should_exit_active')} "
        f"reply_text_len={len(str(result.structured.get('reply_text') or ''))} "
        f"topic_hint={result.structured.get('topic_hint')!r}"
    )

    decision = result.structured
    if decision.get("topic_hint"):
        _mcp.active_sessions.update_topic(adapter_name, group_id, str(decision["topic_hint"]))
    if decision.get("should_exit_active"):
        _mcp.active_sessions.end(adapter_name, group_id)

    if not decision.get("should_reply"):
        # 显式触发 + LLM 选择沉默是「看起来该回但没回」最常见的来源,
        # 提到 info 让群主能扫日志直接看见「不是插件 bug,是 LLM 自己判定的」
        logger.info(
            f"[HERMES reactive] silent: LLM decided should_reply=false "
            f"(group={group_id} user={user_id} explicit={is_explicit_trigger} "
            f"topic_hint={result.structured.get('topic_hint')!r})"
        )
        return result

    reply_text = str(decision.get("reply_text") or "").strip()
    if not reply_text:
        return result

    # B.3: 同 turn 内防重复闸门 — 若 chat() agent loop 期间 last_bot_reply_at
    # 已被推进(即 push_message 在中途答过一次), 抑制本路 submit_decision 的 send。
    # 与入口 cooldown 不同, 这里对显式触发也生效:同 turn 双答属纯重复,与触发性质无关。
    # 注: 直接读 `session.last_bot_reply_at` 而非重新查 active_sessions ──
    # mark_bot_replied 是对同一 dataclass 实例原地写, session 变量持有的就是那个实例。
    # 不查 active_sessions 也回避了 TTL 边界判定与 ended-and-retriggered 罕见竞态。
    if session.last_bot_reply_at > last_bot_reply_at_at_entry:
        logger.info(
            f"[HERMES reactive] suppress submit_decision reply: push_message fired mid-turn "
            f"(group={group_id} user={user_id} explicit={is_explicit_trigger} "
            f"reply_text_len={len(reply_text)})"
        )
        return result

    # 群里明确说话给某人 → at;主动插话 → 不 at
    at_user = user_id if is_explicit_trigger else None
    sent = await send_text_with_media(
        bot=bot,
        target=target,
        text=reply_text,
        media_urls=[],
        at_user_id=at_user,
    )
    logger.debug(
        f"[HERMES reactive] sent adapter={adapter_name} group={group_id} "
        f"ok={sent} text_len={len(reply_text)} at_user={at_user}"
    )

    # 用 send 完成时的 wall clock,不复用入参 now_ms。
    # 入参 now_ms 是 _handle_reactive_path 进函数那一刻抓的, chat() + send 可能耗时
    # 任意长(上游重试 / 上下文压缩 / 工具调用累加),复用入参会让 last_bot_reply_at
    # 远早于真实 send 时间, 让下游 cooldown 闸门(_in_post_reply_cooldown)算出来的
    # elapsed 失真,把窗内的 refire 误判成窗外放过去。
    # 调一次 _now_ms() 拿到 reply_now_ms,三个写操作复用这一个快照,既校正 stale
    # 入参,又避免多次读时钟在三个字段间引入毫秒级偏差。
    if sent and _mcp.message_buffer is not None:
        reply_now_ms = _now_ms()
        _mcp.message_buffer.append(
            BufferedMessage(
                ts=reply_now_ms,
                adapter=adapter_name,
                group_id=group_id,
                user_id=str(bot.self_id),
                nickname="Bot",
                content=reply_text,
                image_urls=[],
                is_bot=True,
            )
        )
        # 注:若 should_exit_active=True,session 已在上方 end(),touch / mark_bot_replied
        # 都是安全 no-op(两者文档统一:session 缺失则 no-op)。
        _mcp.active_sessions.touch(adapter_name, group_id, now_ms=reply_now_ms)
        # B.2: 记下「bot 刚回过」时间戳,供 _handle_reactive_path 入口 + _refire 入口的
        # cooldown 闸门判定。
        _mcp.active_sessions.mark_bot_replied(adapter_name, group_id, now_ms=reply_now_ms)

    return result


async def _handle_passive_path(
    *,
    bot: Bot,
    target,
    adapter_name: str,
    user_id: str,
    group_id: Optional[str],
    text: str,
    image_urls: List[str],
    is_private: bool,
    now_ms: int,
    nickname: Optional[str] = None,
):
    """Passive 外壳:inflight 占位 → _run_passive_turn → 合并重燃。

    与 reactive 同形,key 含 private/group 前缀区分。
    """
    assert _mcp.inflight is not None

    scope_id = user_id if is_private else (group_id or "")
    scope_prefix = "private" if is_private else "group"
    key = (adapter_name, f"{scope_prefix}:{scope_id}")

    current_buffered = BufferedMessage(
        ts=now_ms,
        adapter=adapter_name,
        group_id=group_id,
        user_id=user_id,
        nickname=nickname or user_id,
        content=text,
        image_urls=list(image_urls),
        reply_to_ts=None,
        is_bot=False,
    )

    if _mcp.inflight.try_enter(key, current_buffered, now_ms) == "pending_set":
        return

    should_refire = False
    try:
        result = await _run_passive_turn(
            bot=bot,
            target=target,
            adapter_name=adapter_name,
            user_id=user_id,
            group_id=group_id,
            text=text,
            image_urls=image_urls,
            is_private=is_private,
            now_ms=now_ms,
        )
        should_refire = not (result is not None and result.is_transport_error)
    except Exception:
        logger.exception(f"[HERMES] passive turn raised; dropping pending for {key}")
        should_refire = False
        raise
    finally:
        if not should_refire:
            _mcp.inflight.exit(key)
        else:
            pending = _mcp.inflight.take_pending(key)
            if pending is None or pending.ts <= current_buffered.ts:
                _mcp.inflight.exit(key)
            else:
                asyncio.create_task(
                    _refire(
                        key=key,
                        trigger_msg=pending,
                        depth=1,
                        mode="passive",
                        bot=bot,
                        target=target,
                        adapter_name=adapter_name,
                        group_id=group_id,
                    )
                )


def _in_post_reply_cooldown(adapter_name: str, group_id: str, now_ms: int) -> bool:
    """B: 判断 (adapter, group_id) 是否处于 bot 上次回复后的冷却窗内。

    输入路径 (`_handle_reactive_path`) 和重燃路径 (`_refire`) 共用,确保:
      - 通过 reactive submit_decision 发出的回复 (_run_reactive_turn 末段写 mark_bot_replied)
      - 通过 MCP push_message 发出的回复 (push_message_impl 写 mark_bot_replied)
    两条路径都把后续非显式触发的旁观消息压在窗内,避免「同主题二次答复」。

    冷却仅对**非显式触发**生效——显式 @bot 必须立刻进 chat;调用方自行判断
    `is_explicit_trigger` 后再询问本 helper。

    冷却窗禁用 (`hermes_reactive_post_reply_cooldown_sec == 0`) 或 session 不存在
    /已过期、未记录过 last_bot_reply_at → 返回 False。
    """
    assert _mcp.active_sessions is not None

    cooldown_sec = plugin_config.hermes_reactive_post_reply_cooldown_sec
    if cooldown_sec <= 0:
        return False
    sess = _mcp.active_sessions.get_if_active(adapter_name, group_id, now_ms)
    if sess is None or not sess.last_bot_reply_at:
        return False
    elapsed_ms = now_ms - sess.last_bot_reply_at
    return 0 <= elapsed_ms < cooldown_sec * 1000


async def _handle_reactive_path(
    *,
    bot: Bot,
    target,
    adapter_name: str,
    user_id: str,
    group_id: str,
    text: str,
    image_urls: List[str],
    is_explicit_trigger: bool,
    now_ms: int,
    nickname: Optional[str] = None,
):
    """Reactive 外壳:inflight 占位 → 调 _run_reactive_turn → finally 合并重燃。

    coalesce 语义:in-flight 期间到来的新触发不并发跑,只覆盖 pending 单元;
    本发完成后 take_pending,如有则用 create_task 起一个 _refire 接力,
    本 task 立即 return,不阻塞 NoneBot 事件循环。
    """
    assert _mcp.inflight is not None and _mcp.active_sessions is not None

    # 图片门控:active window + 非显式触发 + 纯图无文本 → 跳过 chat()
    # 理由:LLM 自己的 should_reply 决策对图片要先看完才能定,而看图本身慢。
    # 这种「旁观纯图」最大概率是 should_reply=false,跳过它就是省一次多模态调用。
    # 消息已被 priority=1 perception 写入 MessageBuffer,等下次文本触发能看到。
    in_active = _mcp.active_sessions.is_active(adapter_name, group_id, now_ms)
    if in_active and not is_explicit_trigger and image_urls and not text.strip():
        logger.debug(
            f"[HERMES reactive] skip image-only passive in-window msg "
            f"(group={group_id} user={user_id}); buffered for next text trigger"
        )
        return

    # B: post-reply cooldown — bot 刚在本群发出 reactive 回复 N 秒内,非显式触发的
    # 新消息直接静默。压「我刚说完别人接话→我又凑一句」模式 2。
    # 显式 @bot 触发不受影响(is_explicit_trigger=True 直接旁路)。
    # 写在 inflight try_enter 之前,避免占用 slot 又立刻退出造成 pending 抖动。
    if in_active and not is_explicit_trigger:
        # debug 日志保留入口处,便于运维排查;helper 自己不打日志(refire 路径也会用)
        sess = _mcp.active_sessions.get_if_active(adapter_name, group_id, now_ms)
        cooldown_sec = plugin_config.hermes_reactive_post_reply_cooldown_sec
        logger.debug(
            f"[HERMES reactive] cooldown_check group={group_id} user={user_id} "
            f"sess_exists={sess is not None} "
            f"last_bot_reply_at={sess.last_bot_reply_at if sess else 'n/a'} "
            f"now_ms={now_ms} window_ms={cooldown_sec * 1000}"
        )
        if _in_post_reply_cooldown(adapter_name, group_id, now_ms):
            elapsed_ms = now_ms - (sess.last_bot_reply_at if sess else 0)
            logger.debug(
                f"[HERMES reactive] skip: post-reply cooldown "
                f"(group={group_id} elapsed_ms={elapsed_ms} window_ms={cooldown_sec * 1000})"
            )
            return

    key = (adapter_name, f"group:{group_id}")
    current_buffered = BufferedMessage(
        ts=now_ms,
        adapter=adapter_name,
        group_id=group_id,
        user_id=user_id,
        nickname=nickname or user_id,
        content=text,
        image_urls=list(image_urls),
        reply_to_ts=None,
        is_bot=False,
    )

    if _mcp.inflight.try_enter(key, current_buffered, now_ms) == "pending_set":
        return

    should_refire = False
    try:
        result = await _run_reactive_turn(
            bot=bot,
            target=target,
            adapter_name=adapter_name,
            user_id=user_id,
            nickname=nickname,
            group_id=group_id,
            text=text,
            image_urls=image_urls,
            is_explicit_trigger=is_explicit_trigger,
            now_ms=now_ms,
        )
        should_refire = not (result is not None and result.is_transport_error)
    except Exception:
        logger.exception(f"[HERMES] reactive turn raised; dropping pending for {key}")
        should_refire = False
        raise
    finally:
        if not should_refire:
            _mcp.inflight.exit(key)
        else:
            pending = _mcp.inflight.take_pending(key)
            if pending is None or pending.ts <= current_buffered.ts:
                _mcp.inflight.exit(key)
            else:
                asyncio.create_task(
                    _refire(
                        key=key,
                        trigger_msg=pending,
                        depth=1,
                        mode="reactive",
                        bot=bot,
                        target=target,
                        adapter_name=adapter_name,
                        group_id=group_id,
                    )
                )


async def _refire(
    *,
    key,
    trigger_msg: BufferedMessage,
    depth: int,
    mode: str,
    bot: Bot,
    target,
    adapter_name: str,
    group_id,
):
    """链式重燃。fire-and-forget,深度上限 MAX_REFIRE_DEPTH。"""
    from ..core.inflight import MAX_REFIRE_DEPTH

    assert _mcp.inflight is not None

    if depth > MAX_REFIRE_DEPTH:
        logger.warning(f"[HERMES] refire depth exceeded ({depth}); dropping pending {key}")
        _mcp.inflight.exit(key)
        return

    # now_ms 用 wall-clock 而不是 trigger_msg.ts:_run_*_turn 内部用它做
    # get_if_active 的 TTL 校验、active_sessions.touch 的滑动续期、以及 bot
    # 自己回复的 BufferedMessage.ts。如果用 trigger 时间会导致 touch 后窗口
    # 比预期早 N 秒过期、bot 回复时间戳倒退。trigger_msg.ts 只在 finally 的
    # pending.ts 比对里用,那是消息到达时序而非「当前是几点」。
    refire_now_ms = _now_ms()

    # B: refire 路径同款 post-reply cooldown 闸门。
    # 重燃总是 is_explicit_trigger=False(passive 旁观),所以一律按非显式触发处理。
    # 关键场景:初发 turn 自己没回(submit_decision=silent)但期间 MCP push_message
    # 把 last_bot_reply_at 写了 → 仅靠入口处的闸门挡不住,因为 pending 是上一次
    # 入口处放进来的(进 pending 时还没写 mark)。在这里再判一次,把这条路径补严。
    if (
        mode == "reactive"
        and group_id is not None
        and _in_post_reply_cooldown(adapter_name, str(group_id), refire_now_ms)
    ):
        logger.debug(f"[HERMES reactive] refire skipped by post-reply cooldown (key={key} depth={depth})")
        _mcp.inflight.exit(key)
        return

    should_refire = False
    try:
        if mode == "reactive":
            assert group_id is not None
            result = await _run_reactive_turn(
                bot=bot,
                target=target,
                adapter_name=adapter_name,
                user_id=trigger_msg.user_id,
                nickname=trigger_msg.nickname,
                group_id=group_id,
                text=trigger_msg.content,
                image_urls=list(trigger_msg.image_urls),
                is_explicit_trigger=False,  # 重燃总是 passive 旁观;显式触发已是初发那一发
                now_ms=refire_now_ms,
            )
        else:
            result = await _run_passive_turn(
                bot=bot,
                target=target,
                adapter_name=adapter_name,
                user_id=trigger_msg.user_id,
                group_id=trigger_msg.group_id,
                text=trigger_msg.content,
                image_urls=list(trigger_msg.image_urls),
                is_private=trigger_msg.group_id is None,
                now_ms=refire_now_ms,
            )
        should_refire = not (result is not None and result.is_transport_error)
    except Exception:
        logger.exception(f"[HERMES] refire raised at depth {depth}; dropping pending for {key}")
        should_refire = False
    finally:
        if not should_refire:
            _mcp.inflight.exit(key)
            return
        pending = _mcp.inflight.take_pending(key)
        if pending and pending.ts > trigger_msg.ts:
            asyncio.create_task(
                _refire(
                    key=key,
                    trigger_msg=pending,
                    depth=depth + 1,
                    mode=mode,
                    bot=bot,
                    target=target,
                    adapter_name=adapter_name,
                    group_id=group_id,
                )
            )
        else:
            _mcp.inflight.exit(key)
