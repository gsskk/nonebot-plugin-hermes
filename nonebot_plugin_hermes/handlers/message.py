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


def _extract_image_urls(uni_msg: alconna.UniMessage) -> List[str]:
    urls: List[str] = []
    if uni_msg.has(alconna.Image):
        for img in uni_msg[alconna.Image]:
            url = getattr(img, "url", None)
            if url:
                urls.append(url)
    return urls


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
    image_urls = _extract_image_urls(uni_msg)

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
                nickname=user_id,
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
        matcher.skip()

    # 引用消息提取
    replied_text = ""
    replied_image_urls: List[str] = []
    if hasattr(event, "reply") and event.reply:
        try:
            replied_message = await alconna.UniMessage.generate(message=event.reply.message, bot=bot)
            replied_text = replied_message.extract_plain_text().strip()
            replied_image_urls = _extract_image_urls(replied_message)
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

    image_urls = _extract_image_urls(uni_msg)
    image_urls.extend(replied_image_urls)

    if not msg_text and not image_urls:
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
    system_prompt = None
    if not is_private and group_id and plugin_config.hermes_perception_enabled and _mcp.message_buffer is not None:
        recent = _mcp.message_buffer.get_recent(
            adapter=adapter_name,
            group_id=group_id,
            limit=plugin_config.hermes_perception_buffer,
            before_ts=now_ms,
        )
        system_prompt = build_passive_system_prompt(
            adapter=adapter_name,
            is_private=is_private,
            user_id=user_id,
            group_id=group_id,
            recent_messages=recent,
        )

    result = await hermes_client.chat(
        text=text or " ",
        image_urls=image_urls,
        session_key=session_key,
        user_id=user_id,
        group_id=group_id,
        adapter_name=adapter_name,
        is_private=is_private,
        mode="passive",
        expect_structured=False,
        system_prompt=system_prompt,
    )

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

    recent = _mcp.message_buffer.get_recent(
        adapter=adapter_name,
        group_id=group_id,
        limit=plugin_config.hermes_perception_buffer,
    )

    system_prompt = build_reactive_system_prompt(
        adapter=adapter_name,
        group_id=group_id,
        triggered_by=session.triggered_by,
        triggered_by_nickname=None,
        topic_hint=session.topic_hint,
    )
    user_content = build_reactive_user_content(
        recent_messages=recent,
        current_user_id=user_id,
        current_nickname=user_id,
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

    decision_summary = (
        f"should_reply={result.structured.get('should_reply')} "
        f"should_exit_active={result.structured.get('should_exit_active')} "
        f"topic_hint={result.structured.get('topic_hint')!r}"
    )
    logger.info(f"[HERMES reactive] decision (group={group_id}): {decision_summary}")

    decision = result.structured
    if decision.get("topic_hint"):
        _mcp.active_sessions.update_topic(adapter_name, group_id, str(decision["topic_hint"]))
    if decision.get("should_exit_active"):
        _mcp.active_sessions.end(adapter_name, group_id)

    if not decision.get("should_reply"):
        logger.debug(f"[HERMES reactive] should_reply=false (group={group_id})")
        return result

    reply_text = str(decision.get("reply_text") or "").strip()
    if not reply_text:
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

    # 把 bot 自己的回复回写 MessageBuffer。复用入参 now_ms,避免 send 耗时
    # 后两次 _now_ms() 调用之间出现毫秒级偏差。
    if sent and _mcp.message_buffer is not None:
        _mcp.message_buffer.append(
            BufferedMessage(
                ts=now_ms,
                adapter=adapter_name,
                group_id=group_id,
                user_id=str(bot.self_id),
                nickname="Bot",
                content=reply_text,
                image_urls=[],
                is_bot=True,
            )
        )
        # 注:若 should_exit_active=True,session 已在上方 end(),touch 是安全 no-op
        # (ActiveSessionManager.touch 文档:session 缺失则 no-op)。
        _mcp.active_sessions.touch(adapter_name, group_id, now_ms=now_ms)

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
        nickname=user_id,
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

    key = (adapter_name, f"group:{group_id}")
    current_buffered = BufferedMessage(
        ts=now_ms,
        adapter=adapter_name,
        group_id=group_id,
        user_id=user_id,
        nickname=user_id,
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

    should_refire = False
    try:
        if mode == "reactive":
            assert group_id is not None
            result = await _run_reactive_turn(
                bot=bot,
                target=target,
                adapter_name=adapter_name,
                user_id=trigger_msg.user_id,
                group_id=group_id,
                text=trigger_msg.content,
                image_urls=list(trigger_msg.image_urls),
                is_explicit_trigger=False,  # 重燃总是 passive 旁观;显式触发已是初发那一发
                now_ms=trigger_msg.ts,
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
                now_ms=trigger_msg.ts,
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
