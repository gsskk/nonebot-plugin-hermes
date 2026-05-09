"""push_message: Hermes 反向调用,nonebot 主动发送一条消息到群。

约束(M1):
  - (adapter, group_id) 必须有活跃 reactive session
  - BotRegistry 必须有该 (adapter, group_id) 的 Target
不满足任一条件返回 422 等价错误(由 FastMCP 序列化为 isError=true)。
"""

from __future__ import annotations

import time
from typing import List, Optional

from nonebot import get_bot, logger
from pydantic import BaseModel, Field

from ...core.outbound import send_text_with_media
from ..auth import PushContextError, validate_push_context


class PushMessageInput(BaseModel):
    adapter: str = Field(..., description="Adapter name (lowercased), e.g. 'ob11'")
    group_id: str = Field(..., description="Group ID")
    text: str = Field(..., description="Reply text. Empty allowed only if image_urls non-empty.")
    image_urls: List[str] = Field(default_factory=list, description="Image URLs")
    reply_to_msg_id: Optional[str] = Field(default=None, description="(M1: 不使用,保留位)")
    task_id: Optional[str] = Field(default=None, description="(M1: 不使用,M2 bg_tasks 接入)")


class PushMessageResult(BaseModel):
    ok: bool
    error: Optional[str] = None


async def push_message_impl(
    inp: PushMessageInput,
    *,
    active_sessions,
    bot_registry,
) -> PushMessageResult:
    if not inp.text and not inp.image_urls:
        return PushMessageResult(ok=False, error="text and image_urls both empty")

    now_ms = int(time.time() * 1000)
    try:
        validate_push_context(
            adapter=inp.adapter,
            group_id=inp.group_id,
            active_sessions=active_sessions,
            bot_registry=bot_registry,
            now_ms=now_ms,
        )
    except PushContextError as exc:
        logger.warning(f"[MCP push_message] context invalid: {exc}")
        return PushMessageResult(ok=False, error=str(exc))

    entry = bot_registry.get(inp.adapter, "group", inp.group_id)
    assert entry is not None  # validated above

    try:
        bot = get_bot(entry.bot_self_id)
    except (KeyError, ValueError) as exc:
        logger.warning(f"[MCP push_message] bot offline self_id={entry.bot_self_id}: {exc}")
        return PushMessageResult(ok=False, error=f"bot offline: {entry.bot_self_id}")

    success = await send_text_with_media(
        bot=bot,
        target=entry.target,
        text=inp.text,
        media_urls=inp.image_urls,
        at_user_id=None,
    )
    if not success:
        return PushMessageResult(ok=False, error="send failed (see nonebot log)")

    # 滑动续期
    active_sessions.touch(inp.adapter, inp.group_id, now_ms=now_ms)
    return PushMessageResult(ok=True)
