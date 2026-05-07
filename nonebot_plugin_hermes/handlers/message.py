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


# 监听普通消息，设置优先级 98 (比默认 99 高)，在真正响应时阻断后续处理
receive_message = on_message(
    rule=Rule(_ignore_rule),
    priority=98,
    block=True,
)


# 被动感知：监听所有消息（非阻塞），仅用于记录上下文背景
# 优先级设为 1，确保在所有可能阻断事件的插件之前执行记录
perception_message = on_message(priority=1, block=False)


@perception_message.handle()
async def handle_perception(bot: Bot, event: Event):
    """静默记录消息到本地缓存，不触发 AI 回复"""
    if not plugin_config.hermes_perception_enabled:
        return

    try:
        target = alconna.get_target()
        if target.private:
            return
        adapter_name = get_adapter_name(target)
        user_id = event.get_user_id()
    except Exception:
        return

    # 忽略来自自身的消息
    if user_id == str(bot.self_id):
        return

    # 提取消息内容
    image_urls: List[str] = []
    try:
        uni_msg = alconna.UniMessage.generate_without_reply(event=event, bot=bot)
        msg_text = uni_msg.extract_plain_text().strip()

        # 提取图片 URL
        if uni_msg.has(alconna.Image):
            for img in uni_msg[alconna.Image]:
                url = getattr(img, "url", None)
                if url:
                    image_urls.append(url)

        # 处理图片占位
        if image_urls and plugin_config.hermes_perception_image_mode != "none":
            placeholder = " [图片]"
            if msg_text:
                msg_text += placeholder
            else:
                msg_text = placeholder
    except Exception:
        return

    if not msg_text and not image_urls:
        return

    group_id = None if target.private else target.id

    # 记录到会话历史
    session_manager.record_history(
        adapter_name=adapter_name,
        is_private=target.private,
        user_id=user_id,
        group_id=group_id,
        sender_name=user_id,
        content=msg_text,
        image_urls=image_urls,
    )
    logger.debug(f"[PERCEPTION] 已记录历史: {user_id}: {msg_text[:50]}...")


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

    # 提取引用消息中的内容
    replied_text = ""
    replied_image_urls: List[str] = []
    if hasattr(event, "reply") and event.reply:
        try:
            # 引用消息的生成通常是异步的 (针对 message 属性)
            replied_message = await alconna.UniMessage.generate(message=event.reply.message, bot=bot)

            # 提取引用文本
            replied_text = replied_message.extract_plain_text().strip()

            # 提取引用图片
            if replied_message.has(alconna.Image):
                for img in replied_message[alconna.Image]:
                    url = getattr(img, "url", None)
                    if url:
                        replied_image_urls.append(url)
                        logger.debug(f"[HERMES] 引用消息图片 URL: {url[:50]!r}")
                if not replied_text:
                    replied_text = "[图片]"
        except Exception as e:
            logger.warning(f"[HERMES] 提取引用消息失败: {e}")

    # 生成当前消息对象
    try:
        uni_msg = alconna.UniMessage.generate_without_reply(event=event, bot=bot)
    except Exception:
        matcher.skip()

    # 提取纯文本
    msg_text = uni_msg.extract_plain_text().strip()

    # 如果有引用文本，合并到主消息中提供上下文
    if replied_text:
        msg_text = f"(引用: {replied_text}) {msg_text}".strip()

    # 提取图片 URL
    image_urls: List[str] = []
    if uni_msg.has(alconna.Image):
        for img in uni_msg[alconna.Image]:
            url = getattr(img, "url", None)
            if url:
                image_urls.append(url)
                logger.debug(f"[HERMES] 当前消息图片 URL: {url[:50]!r}")
            else:
                logger.debug(f"[HERMES] 图片段无 url 属性, img={img!r}")

    # 合并引用消息中的图片
    image_urls.extend(replied_image_urls)

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

    # --- 获取历史背景上下文 (Passive Perception) ---
    history_text, history_images = "", []
    if not target.private:
        history_text, history_images = session_manager.get_history_context(
            adapter_name=adapter_name,
            is_private=target.private,
            user_id=user_id,
            group_id=group_id,
            skip_last=True,
        )
    if history_text:
        logger.debug(f"[PERCEPTION] 成功注入历史背景, history_image_count={len(history_images)}")

    logger.info(
        f"[HERMES] [{adapter_name}] {'私聊' if target.private else f'群聊({group_id})'} "
        f"{user_id}: {msg_text[:80].replace(chr(10), ' ')}"
        f"{f' [+{len(image_urls)} 当前图]' if image_urls else ''}"
        f"{f' [+{len(history_images)} 历史图]' if history_images else ''}"
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
        historical_text=history_text,
        historical_image_urls=history_images,
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

        # 将 Bot 自身的回复记录到历史（被动感知上下文）
        if plugin_config.hermes_perception_enabled and not target.private:
            session_manager.record_history(
                adapter_name=adapter_name,
                is_private=target.private,
                user_id=str(bot.self_id),
                group_id=group_id,
                sender_name="Bot",
                content=reply_text,
                image_urls=media_urls,
            )
    except Exception as exc:
        logger.error(f"[HERMES] 发送回复失败: {exc}")
