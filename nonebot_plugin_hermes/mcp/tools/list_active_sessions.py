"""list_active_sessions: 列出所有活跃群。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ListActiveSessionsInput(BaseModel):
    adapter: str | None = Field(default=None, description="筛选适配器,None 返回所有")


class ActiveSessionView(BaseModel):
    adapter: str
    group_id: str
    triggered_by: str
    started_at: int
    last_active_at: int
    expires_at: int
    topic_hint: str | None = None


class ListActiveSessionsResult(BaseModel):
    sessions: list[ActiveSessionView]


async def list_active_sessions_impl(
    inp: ListActiveSessionsInput,
    *,
    active_sessions,
) -> ListActiveSessionsResult:
    rows = active_sessions.list(adapter=inp.adapter)
    views = [
        ActiveSessionView(
            adapter=r.adapter,
            group_id=r.group_id,
            triggered_by=r.triggered_by,
            started_at=r.started_at,
            last_active_at=r.last_active_at,
            expires_at=r.expires_at,
            topic_hint=r.topic_hint,
        )
        for r in rows
    ]
    return ListActiveSessionsResult(sessions=views)
