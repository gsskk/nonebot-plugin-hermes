"""统一出向发送器。

封装 alconna UniMessage 拼装 + send。
被两条路径共享:
  1. handlers/message.py 中收到结构化 reply_text 后发送
  2. mcp/tools/push_message.py 反向通道收到 push_message 后发送
"""

from __future__ import annotations

from typing import Optional, Sequence

import nonebot_plugin_alconna as alconna
from nonebot import logger
from nonebot.adapters import Bot

from ..config import plugin_config


async def send_text_with_media(
    *,
    bot: Bot,
    target: alconna.Target,
    text: str,
    media_urls: Sequence[str] = (),
    at_user_id: Optional[str] = None,
    reply_to_msg_id: Optional[str] = None,
) -> bool:
    """组装并发送一条消息，返回是否发送成功。

    - target 是 alconna Target（只在内存可用）
    - 群聊默认在文本前加 At(at_user_id)；为 None 不 at
    - reply_to_msg_id：当前 alconna Reply 段在多 adapter 下兼容性不一，M1 不强制使用，
      保留此参数供未来兼容扩展
    """
    msg = alconna.UniMessage()

    if not target.private and at_user_id:
        msg += alconna.UniMessage([alconna.At("user", at_user_id), " "])

    if text:
        max_len = plugin_config.hermes_max_length
        if len(text) > max_len:
            text = text[:max_len] + "\n\n…（消息过长，已截断）"
        msg += alconna.UniMessage(text)

    for u in media_urls:
        if u.startswith(("http://", "https://")):
            msg += alconna.UniMessage(alconna.Image(url=u))

    try:
        await msg.send(target=target, bot=bot)
        logger.debug(f"[OUTBOUND] sent target={target} text_len={len(text)} media={len(media_urls)}")
        return True
    except Exception as exc:
        logger.error(f"[OUTBOUND] 发送失败 target={target}: {exc}")
        return False
