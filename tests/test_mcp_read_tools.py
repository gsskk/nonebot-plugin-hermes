"""Unit tests for mcp/tools/list_active_sessions.py and get_recent_messages.py.

Uses real ActiveSessionManager / MessageBuffer — no mocking needed since
both tools are pure read functions that accept manager objects as kwargs.
"""

from __future__ import annotations

import pytest

from nonebot_plugin_hermes.core.active_session import ActiveSessionManager
from nonebot_plugin_hermes.core.message_buffer import BufferedMessage, MessageBuffer
from nonebot_plugin_hermes.mcp.tools.get_recent_messages import (
    GetRecentMessagesInput,
    GetRecentMessagesResult,
    RecentMessageView,
    get_recent_messages_impl,
)
from nonebot_plugin_hermes.mcp.tools.list_active_sessions import (
    ActiveSessionView,
    ListActiveSessionsInput,
    ListActiveSessionsResult,
    list_active_sessions_impl,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_mgr(*entries) -> ActiveSessionManager:
    """Build an ActiveSessionManager with the given (adapter, group_id, user_id) tuples."""
    mgr = ActiveSessionManager(default_ttl_sec=300)
    for adapter, group_id, user_id in entries:
        mgr.trigger(adapter, group_id, user_id, now_ms=0)
    return mgr


def _msg(
    ts: int,
    adapter: str = "ob11",
    group_id: str = "g1",
    user_id: str = "u1",
    content: str = "hello",
    image_urls: list[str] | None = None,
    is_bot: bool = False,
) -> BufferedMessage:
    return BufferedMessage(
        ts=ts,
        adapter=adapter,
        group_id=group_id,
        user_id=user_id,
        nickname=user_id,
        content=content,
        image_urls=image_urls or [],
        reply_to_ts=None,
        is_bot=is_bot,
    )


def _make_buffer(*msgs: BufferedMessage) -> MessageBuffer:
    buf = MessageBuffer(per_group_cap=200, total_groups_cap=50)
    for m in msgs:
        buf.append(m)
    return buf


# ---------------------------------------------------------------------------
# list_active_sessions_impl tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_active_sessions_empty():
    """Returns empty list when no sessions exist."""
    mgr = ActiveSessionManager(default_ttl_sec=300)
    inp = ListActiveSessionsInput(adapter=None)
    result = await list_active_sessions_impl(inp, active_sessions=mgr)
    assert isinstance(result, ListActiveSessionsResult)
    assert result.sessions == []


@pytest.mark.asyncio
async def test_list_active_sessions_no_filter_returns_all():
    """With adapter=None, returns all sessions regardless of adapter."""
    mgr = _make_session_mgr(("ob11", "g1", "u1"), ("kook", "g2", "u2"), ("ob11", "g3", "u3"))
    inp = ListActiveSessionsInput(adapter=None)
    result = await list_active_sessions_impl(inp, active_sessions=mgr)
    assert isinstance(result, ListActiveSessionsResult)
    assert len(result.sessions) == 3
    group_ids = {v.group_id for v in result.sessions}
    assert group_ids == {"g1", "g2", "g3"}


@pytest.mark.asyncio
async def test_list_active_sessions_with_adapter_filter():
    """With adapter='ob11', returns only ob11 sessions."""
    mgr = _make_session_mgr(("ob11", "g1", "u1"), ("kook", "g2", "u2"), ("ob11", "g3", "u3"))
    inp = ListActiveSessionsInput(adapter="ob11")
    result = await list_active_sessions_impl(inp, active_sessions=mgr)
    assert len(result.sessions) == 2
    for v in result.sessions:
        assert v.adapter == "ob11"


@pytest.mark.asyncio
async def test_list_active_sessions_view_fields_match_session():
    """ActiveSessionView fields are correctly mapped from ActiveSession."""
    mgr = ActiveSessionManager(default_ttl_sec=300)
    session = mgr.trigger("ob11", "g1", "u42", now_ms=5_000, topic_hint="rust async")
    inp = ListActiveSessionsInput(adapter=None)
    result = await list_active_sessions_impl(inp, active_sessions=mgr)
    assert len(result.sessions) == 1
    v = result.sessions[0]
    assert isinstance(v, ActiveSessionView)
    assert v.adapter == session.adapter
    assert v.group_id == session.group_id
    assert v.triggered_by == session.triggered_by
    assert v.started_at == session.started_at
    assert v.last_active_at == session.last_active_at
    assert v.expires_at == session.expires_at
    assert v.topic_hint == "rust async"


@pytest.mark.asyncio
async def test_list_active_sessions_topic_hint_none_allowed():
    """topic_hint=None is valid (str | None field)."""
    mgr = ActiveSessionManager(default_ttl_sec=300)
    mgr.trigger("ob11", "g1", "u1", now_ms=0, topic_hint=None)
    inp = ListActiveSessionsInput(adapter=None)
    result = await list_active_sessions_impl(inp, active_sessions=mgr)
    assert result.sessions[0].topic_hint is None


# ---------------------------------------------------------------------------
# get_recent_messages_impl tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_recent_messages_empty_bucket():
    """Returns empty list for unknown (adapter, group_id)."""
    buf = MessageBuffer()
    inp = GetRecentMessagesInput(adapter="ob11", group_id="g_unknown")
    result = await get_recent_messages_impl(inp, message_buffer=buf)
    assert isinstance(result, GetRecentMessagesResult)
    assert result.messages == []


@pytest.mark.asyncio
async def test_get_recent_messages_returns_newest_first():
    """Messages are returned newest-first (matching MessageBuffer.get_recent ordering)."""
    buf = _make_buffer(_msg(100), _msg(200), _msg(300))
    inp = GetRecentMessagesInput(adapter="ob11", group_id="g1", limit=10)
    result = await get_recent_messages_impl(inp, message_buffer=buf)
    assert [v.ts for v in result.messages] == [300, 200, 100]


@pytest.mark.asyncio
async def test_get_recent_messages_limit_clamped_to_config_cap(monkeypatch):
    """limit is clamped to hermes_mcp_recent_limit_max even when Pydantic max (100) allows more.

    We monkeypatch plugin_config.hermes_mcp_recent_limit_max to 3 and verify
    that a request with limit=100 only returns 3 messages.
    """
    import nonebot_plugin_hermes.mcp.tools.get_recent_messages as mod

    buf = _make_buffer(*[_msg(ts) for ts in range(1, 11)])  # 10 messages
    monkeypatch.setattr(mod.plugin_config, "hermes_mcp_recent_limit_max", 3)
    inp = GetRecentMessagesInput(adapter="ob11", group_id="g1", limit=100)
    result = await get_recent_messages_impl(inp, message_buffer=buf)
    assert len(result.messages) == 3


@pytest.mark.asyncio
async def test_get_recent_messages_before_ts_filter():
    """before_ts is passed through to MessageBuffer.get_recent (exclusive upper bound)."""
    buf = _make_buffer(_msg(100), _msg(200), _msg(300), _msg(400))
    inp = GetRecentMessagesInput(adapter="ob11", group_id="g1", limit=10, before_ts=300)
    result = await get_recent_messages_impl(inp, message_buffer=buf)
    # Should only include ts < 300: ts=200, ts=100
    assert [v.ts for v in result.messages] == [200, 100]


@pytest.mark.asyncio
async def test_get_recent_messages_view_fields_mapped_correctly():
    """RecentMessageView fields are correctly mapped from BufferedMessage."""
    buf = _make_buffer(
        _msg(
            ts=999,
            adapter="ob11",
            group_id="g1",
            user_id="u42",
            content="hello world",
            image_urls=["https://example.com/img.png"],
            is_bot=False,
        )
    )
    inp = GetRecentMessagesInput(adapter="ob11", group_id="g1", limit=1)
    result = await get_recent_messages_impl(inp, message_buffer=buf)
    assert len(result.messages) == 1
    v = result.messages[0]
    assert isinstance(v, RecentMessageView)
    assert v.ts == 999
    assert v.user_id == "u42"
    assert v.nickname == "u42"
    assert v.content == "hello world"
    assert v.image_urls == ["https://example.com/img.png"]
    assert v.is_bot is False


@pytest.mark.asyncio
async def test_get_recent_messages_image_urls_is_copy():
    """image_urls in RecentMessageView is a copy, not the original list (defensive mutation guard)."""
    original_urls = ["https://example.com/img.png"]
    buf = _make_buffer(_msg(ts=100, image_urls=original_urls))
    inp = GetRecentMessagesInput(adapter="ob11", group_id="g1", limit=1)
    result = await get_recent_messages_impl(inp, message_buffer=buf)
    v = result.messages[0]
    # Mutating the view's image_urls should not affect the original list in the buffer
    v.image_urls.append("https://example.com/extra.png")
    assert original_urls == ["https://example.com/img.png"]
