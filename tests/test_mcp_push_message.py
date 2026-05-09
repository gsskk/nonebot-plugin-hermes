"""Unit tests for mcp/tools/push_message.py.

Early-return paths (empty payload, no active session, unknown target) are
exercised without mocking send_text_with_media or get_bot — execution stops
before those calls.  The success path and the bot-offline path require
lightweight monkeypatching.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nonebot_plugin_hermes.core.active_session import ActiveSessionManager
from nonebot_plugin_hermes.core.bot_registry import BotRegistry
from nonebot_plugin_hermes.mcp.tools.push_message import (
    PushMessageInput,
    PushMessageResult,
    push_message_impl,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeTarget:
    private = False


def _make_inp(**kwargs) -> PushMessageInput:
    defaults = dict(adapter="ob11", group_id="g1", text="hello", image_urls=[])
    defaults.update(kwargs)
    return PushMessageInput(**defaults)


def _populated_managers(*, now_ms: int = 0):
    """Return (ActiveSessionManager, BotRegistry) with ob11/g1 populated."""
    am = ActiveSessionManager(default_ttl_sec=300)
    br = BotRegistry()
    am.trigger("ob11", "g1", "u1", now_ms=now_ms)
    br.upsert("ob11", "group", "g1", "bot-001", _FakeTarget(), ts=now_ms)
    return am, br


# ---------------------------------------------------------------------------
# Early-return path 1: both text and image_urls empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_returns_error_when_text_and_images_both_empty():
    am, br = _populated_managers()
    inp = _make_inp(text="", image_urls=[])
    result = await push_message_impl(inp, active_sessions=am, bot_registry=br)
    assert isinstance(result, PushMessageResult)
    assert result.ok is False
    assert result.error == "text and image_urls both empty"


# ---------------------------------------------------------------------------
# Early-return path 2: no active reactive session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_returns_error_when_no_active_session():
    am = ActiveSessionManager(default_ttl_sec=300)
    br = BotRegistry()
    # BotRegistry has the target but ActiveSessionManager is empty
    br.upsert("ob11", "group", "g1", "bot-001", _FakeTarget(), ts=0)

    inp = _make_inp()
    result = await push_message_impl(inp, active_sessions=am, bot_registry=br)
    assert result.ok is False
    assert "no active reactive session" in (result.error or "")


# ---------------------------------------------------------------------------
# Early-return path 3: session active but target unknown in BotRegistry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_returns_error_when_target_unknown():
    am = ActiveSessionManager(default_ttl_sec=300)
    br = BotRegistry()
    # ActiveSessionManager has the session but BotRegistry is empty
    am.trigger("ob11", "g1", "u1", now_ms=0)

    inp = _make_inp()
    result = await push_message_impl(inp, active_sessions=am, bot_registry=br)
    assert result.ok is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# Bot-offline path: get_bot raises KeyError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_returns_error_when_bot_offline():
    am, br = _populated_managers()
    inp = _make_inp()

    with (
        patch("nonebot_plugin_hermes.mcp.tools.push_message.get_bot", side_effect=KeyError("bot-001")),
        patch("nonebot_plugin_hermes.mcp.tools.push_message.time") as mock_time,
    ):
        mock_time.time.return_value = 1.0  # 1000 ms — within TTL
        result = await push_message_impl(inp, active_sessions=am, bot_registry=br)

    assert result.ok is False
    assert "bot offline" in (result.error or "")


# ---------------------------------------------------------------------------
# Success path: send succeeds → ok=True and session is touched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_success_touches_session():
    now_ms = 0
    am, br = _populated_managers(now_ms=now_ms)
    inp = _make_inp()

    fake_bot = MagicMock()

    with (
        patch("nonebot_plugin_hermes.mcp.tools.push_message.get_bot", return_value=fake_bot),
        patch(
            "nonebot_plugin_hermes.mcp.tools.push_message.send_text_with_media",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("nonebot_plugin_hermes.mcp.tools.push_message.time") as mock_time,
    ):
        # Fix time so now_ms used inside push_message_impl is within TTL
        mock_time.time.return_value = 1.0  # 1000 ms — well within 300-s TTL
        result = await push_message_impl(inp, active_sessions=am, bot_registry=br)

    assert result.ok is True
    assert result.error is None
    # Session should still be active (touch was called)
    assert am.is_active("ob11", "g1", now_ms=2_000)  # 2 s after trigger, still active


# ---------------------------------------------------------------------------
# send_text_with_media returns False → error reported
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_returns_error_when_send_fails():
    am, br = _populated_managers()
    inp = _make_inp()

    fake_bot = MagicMock()

    with (
        patch("nonebot_plugin_hermes.mcp.tools.push_message.get_bot", return_value=fake_bot),
        patch(
            "nonebot_plugin_hermes.mcp.tools.push_message.send_text_with_media",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("nonebot_plugin_hermes.mcp.tools.push_message.time") as mock_time,
    ):
        mock_time.time.return_value = 1.0
        result = await push_message_impl(inp, active_sessions=am, bot_registry=br)

    assert result.ok is False
    assert "send failed" in (result.error or "")


# ---------------------------------------------------------------------------
# image_urls only (text empty) is allowed when images are present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_accepts_image_only_message():
    am, br = _populated_managers()
    inp = _make_inp(text="", image_urls=["https://example.com/img.png"])

    fake_bot = MagicMock()

    with (
        patch("nonebot_plugin_hermes.mcp.tools.push_message.get_bot", return_value=fake_bot),
        patch(
            "nonebot_plugin_hermes.mcp.tools.push_message.send_text_with_media",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("nonebot_plugin_hermes.mcp.tools.push_message.time") as mock_time,
    ):
        mock_time.time.return_value = 1.0
        result = await push_message_impl(inp, active_sessions=am, bot_registry=br)

    assert result.ok is True
