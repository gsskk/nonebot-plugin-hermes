"""list_active_sessions: 列出所有活跃群。"""

from __future__ import annotations

import time

from pydantic import BaseModel, Field


class ListActiveSessionsInput(BaseModel):
    adapter: str | None = Field(default=None, description="筛选适配器,None 返回所有")


class ActiveSessionView(BaseModel):
    adapter: str
    group_id: str
    triggered_by: str
    started_at: int = Field(..., description="Unix timestamp (ms)")
    last_active_at: int = Field(..., description="Unix timestamp (ms)")
    expires_at: int = Field(..., description="Unix timestamp (ms);call returns only未过期 session")
    topic_hint: str | None = None


class ListActiveSessionsResult(BaseModel):
    sessions: list[ActiveSessionView]


async def list_active_sessions_impl(
    inp: ListActiveSessionsInput,
    *,
    active_sessions,
    now_ms: int | None = None,
) -> ListActiveSessionsResult:
    """列出未过期的活跃 session。

    `ActiveSessionManager.list()` 本身不做 TTL 过滤(它是裸 dict 扫描);
    Task 16 的 cron sweep_expired 周期性清理(默认 30s/次),意味着 list 与 sweep
    之间存在最长 30s 的"陈旧条目"窗口。本工具在工具层主动按 expires_at > now_ms
    过滤,确保 Hermes 拿到的"活跃"列表与 push_message 的 validate_push_context
    口径一致——避免 Hermes 看到一个陈旧 session、立刻 push、然后 422。

    `now_ms` 参数主要用于测试注入;生产调用走 `time.time()`。
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
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
        if r.expires_at > now_ms
    ]
    return ListActiveSessionsResult(sessions=views)
