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

# 截断 suffix 长度 = 13 字符;最终消息 = max_len + 13 字符,故意溢出 max_len。
# 所有已知 adapter 上限 ≥ 4500,默认 max_len=4000,溢出安全。
_TRUNCATION_SUFFIX = "\n\n…（消息过长,已截断）"


async def send_text_with_media(
    *,
    bot: Bot,
    target: alconna.Target,
    text: str,
    media_urls: Sequence[str] = (),
    at_user_id: Optional[str] = None,
    reply_to_msg_id: Optional[str] = None,  # noqa: ARG001  forward-compat
) -> bool:
    """组装并发送一条消息,返回是否发送成功。

    - target 是 alconna Target(只在内存可用)
    - 群聊默认在文本前加 At(at_user_id);为 None 不 at
    - reply_to_msg_id: alconna Reply 段在多 adapter 下兼容性不一,M1 不强制使用;
      保留此参数供未来兼容扩展(noqa: ARG001 直到接入)。
    - 空消息(text='' 且无 http/https 媒体)直接返回 False 不发,防 Task 12 push 路径
      在 Hermes 回空时构造空 UniMessage 发送出去。
    """
    msg = alconna.UniMessage()

    if not target.private and at_user_id:
        msg += alconna.UniMessage([alconna.At("user", at_user_id), " "])

    original_len = len(text)
    truncated = False
    if text:
        max_len = plugin_config.hermes_max_length
        if original_len > max_len:
            text = text[:max_len] + _TRUNCATION_SUFFIX
            truncated = True
        msg += alconna.UniMessage(text)

    sent_media_count = 0
    for u in media_urls:
        if u.startswith(("http://", "https://")):
            msg += alconna.UniMessage(alconna.Image(url=u))
            sent_media_count += 1

    # 空消息守卫:连 At 都没有(私聊 / 没传 at_user_id),text 空,无合法媒体 → 不发
    if not msg:
        logger.warning(
            f"[OUTBOUND] empty message skipped target={target} "
            f"(text_len={original_len} input_media={len(media_urls)} "
            f"valid_media={sent_media_count})"
        )
        return False

    try:
        await msg.send(target=target, bot=bot)
        logger.debug(
            f"[OUTBOUND] sent target={target} text_len={original_len} "
            f"truncated={truncated} media_sent={sent_media_count}/{len(media_urls)}"
        )
        return True
    except Exception as exc:
        logger.error(f"[OUTBOUND] 发送失败 target={target}: {exc}")
        return False
