"""
消息处理器

监听普通消息，根据触发规则调用 Hermes API 并回复。
"""

from __future__ import annotations

from typing import List

import nonebot_plugin_alconna as alconna
from nonebot import on_message, logger
from nonebot.adapters import Bot, Event
from nonebot.rule import Rule
from nonebot.matcher import Matcher

from ..config import plugin_config
from ..core.hermes_client import hermes_client
from ..core.session import session_manager
from ..utils import get_adapter_name, check_isolation


async def _ignore_rule(event: Event) -> bool:
    """过滤不需要处理的消息"""
    # 检查忽略前缀
    try:
        msg_text = event.get_plaintext().strip()
    except Exception:
        return False

    if not msg_text:
        return True  # 空消息也传递（可能有图片）

    for prefix in plugin_config.hermes_ignore_prefix:
        if msg_text.startswith(prefix):
            return False

    return True


# 监听普通消息，设置优先级 98 (比默认 99 高)，在真正响应时阻断 Dify
receive_message = on_message(
    rule=Rule(_ignore_rule),
    priority=98,
    block=True,
)


@receive_message.handle()
async def handle_message(bot: Bot, event: Event, matcher: Matcher):
    """处理接收到的消息"""
    try:
        target = alconna.get_target()
    except Exception:
        matcher.skip()

    adapter_name = get_adapter_name(target)
    user_id = event.get_user_id() or "user"

    # 忽略来自自身的消息
    if user_id == str(bot.self_id):
        matcher.skip()

    # 生成统一消息对象
    try:
        uni_msg = alconna.UniMessage.generate_without_reply(event=event, bot=bot)
    except Exception:
        matcher.skip()

    # 提取纯文本
    msg_text = uni_msg.extract_plain_text().strip()

    # 提取图片 URL
    image_urls: List[str] = []
    if uni_msg.has(alconna.Image):
        for img in uni_msg[alconna.Image]:
            url = getattr(img, "url", None)
            if url:
                image_urls.append(url)
                logger.debug(f"[HERMES] 图片 URL 样本 (前50字符): {url[:50]!r}")
            else:
                logger.debug(f"[HERMES] 图片段无 url 属性, img={img!r}")

    # 空消息且无图片则跳过
    if not msg_text and not image_urls:
        matcher.skip()

    # --- 触发判断 ---
    if not check_isolation(event, target):
        matcher.skip()

    group_id = None if target.private else target.id

    if not target.private:
        is_mentioned = event.is_tome()

        # 检测消息中是否有显式 @bot
        if not is_mentioned and uni_msg.has(alconna.At):
            for seg in uni_msg[alconna.At]:
                if str(seg.target) == str(bot.self_id):
                    is_mentioned = True
                    break

        trigger_mode = plugin_config.hermes_group_trigger

        if trigger_mode == "at":
            if not is_mentioned:
                matcher.skip()
        elif trigger_mode == "keyword":
            matched_kw = False
            for kw in plugin_config.hermes_keywords:
                if msg_text.startswith(kw):
                    msg_text = msg_text[len(kw) :].strip()
                    matched_kw = True
                    break
            if not matched_kw and not is_mentioned:
                matcher.skip()
        # "all" 模式：始终响应

        if not msg_text and not image_urls:
            matcher.skip()

    # --- 构建 session key ---
    group_id = None if target.private else target.id
    session_key = session_manager.get_session_key(
        adapter_name=adapter_name,
        is_private=target.private,
        user_id=user_id,
        group_id=group_id,
    )

    logger.info(
        f"[HERMES] [{adapter_name}] {'私聊' if target.private else f'群聊({group_id})'} "
        f"{user_id}: {msg_text[:80]}"
        f"{f' [+{len(image_urls)} 图片]' if image_urls else ''}"
    )

    # --- 调用 Hermes API ---
    reply_text, media_urls = await hermes_client.chat(
        text=msg_text or " ",  # 有图无字时发空格确保 API 正常
        image_urls=image_urls,
        session_key=session_key,
        user_id=user_id,
        group_id=group_id,
        adapter_name=adapter_name,
        is_private=target.private,
    )

    if not reply_text and not media_urls:
        return

    # --- 构建回复消息 ---
    reply_msg = alconna.UniMessage()

    # 群聊 @回复用户
    if not target.private:
        reply_msg += alconna.UniMessage([alconna.At("user", user_id), " "])

    # 文本内容（截断长消息）
    if reply_text:
        max_len = plugin_config.hermes_max_length
        if len(reply_text) > max_len:
            reply_text = reply_text[:max_len] + "\n\n…（消息过长，已截断）"
        reply_msg += alconna.UniMessage(reply_text)

    # 图片内容
    for url in media_urls:
        if url.startswith(("http://", "https://")):
            reply_msg += alconna.UniMessage(alconna.Image(url=url))

    # --- 发送 ---
    try:
        await reply_msg.send(target=target, bot=bot)
        logger.debug(f"[HERMES] 回复已发送 ({len(reply_text)} 字, {len(media_urls)} 媒体)")
    except Exception as exc:
        logger.error(f"[HERMES] 发送回复失败: {exc}")
