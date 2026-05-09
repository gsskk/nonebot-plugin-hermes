"""get_recent_messages: 拉取一个群的最近 N 条消息。

skill 文档明示此工具贵,慎用。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...config import plugin_config


class GetRecentMessagesInput(BaseModel):
    adapter: str
    group_id: str = Field(..., description="Group ID. M1: 私聊不支持,group_id 必须非空。")
    limit: int = Field(default=20, ge=1, le=100)
    before_ts: int | None = Field(
        default=None,
        description="Unix timestamp (ms);只返回 ts 严格小于此值的消息(分页拉取早于某点的历史)",
    )


class RecentMessageView(BaseModel):
    ts: int = Field(..., description="Unix timestamp (ms)")
    user_id: str
    nickname: str
    content: str
    image_urls: list[str]
    is_bot: bool


class GetRecentMessagesResult(BaseModel):
    messages: list[RecentMessageView]


async def get_recent_messages_impl(
    inp: GetRecentMessagesInput,
    *,
    message_buffer,
) -> GetRecentMessagesResult:
    cap = plugin_config.hermes_mcp_recent_limit_max
    effective_limit = min(inp.limit, cap)
    rows = message_buffer.get_recent(
        adapter=inp.adapter,
        group_id=inp.group_id,
        limit=effective_limit,
        before_ts=inp.before_ts,
    )
    views = [
        RecentMessageView(
            ts=m.ts,
            user_id=m.user_id,
            nickname=m.nickname,
            content=m.content,
            image_urls=list(m.image_urls),
            is_bot=m.is_bot,
        )
        for m in rows
    ]
    return GetRecentMessagesResult(messages=views)
