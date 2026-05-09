"""MCP 鉴权与上下文校验测试。"""

from __future__ import annotations

import pytest

from nonebot_plugin_hermes.core.active_session import ActiveSessionManager
from nonebot_plugin_hermes.core.bot_registry import BotRegistry
from nonebot_plugin_hermes.mcp.auth import (
    AuthError,
    PushContextError,
    check_bearer,
    validate_push_context,
)


class _FakeTarget:
    private = False


def test_check_bearer_accepts_matching_token():
    check_bearer("Bearer secret-xyz", expected="secret-xyz")  # 不抛


def test_check_bearer_rejects_missing_header():
    with pytest.raises(AuthError):
        check_bearer(None, expected="secret-xyz")


def test_check_bearer_rejects_wrong_token():
    with pytest.raises(AuthError):
        check_bearer("Bearer wrong", expected="secret-xyz")


def test_check_bearer_rejects_non_bearer_scheme():
    with pytest.raises(AuthError):
        check_bearer("Basic abc", expected="secret-xyz")


def test_check_bearer_passes_when_no_expected_token_configured():
    # 配置无 token = 不鉴权(开发模式)
    check_bearer(None, expected="")  # 不抛


def test_validate_push_context_active_with_known_target():
    am = ActiveSessionManager(default_ttl_sec=60)
    br = BotRegistry()
    am.trigger("ob11", "g1", "u1", now_ms=0)
    br.upsert("ob11", "group", "g1", "bot", _FakeTarget(), ts=0)

    # 不抛
    validate_push_context(
        adapter="ob11",
        group_id="g1",
        active_sessions=am,
        bot_registry=br,
        now_ms=30_000,
    )


def test_validate_push_context_no_active_session_raises():
    am = ActiveSessionManager(default_ttl_sec=60)
    br = BotRegistry()
    br.upsert("ob11", "group", "g1", "bot", _FakeTarget(), ts=0)
    with pytest.raises(PushContextError):
        validate_push_context(
            adapter="ob11",
            group_id="g1",
            active_sessions=am,
            bot_registry=br,
            now_ms=30_000,
        )


def test_validate_push_context_unknown_target_raises():
    am = ActiveSessionManager(default_ttl_sec=60)
    br = BotRegistry()
    am.trigger("ob11", "g1", "u1", now_ms=0)
    with pytest.raises(PushContextError):
        validate_push_context(
            adapter="ob11",
            group_id="g1",
            active_sessions=am,
            bot_registry=br,
            now_ms=30_000,
        )


def test_validate_push_context_expired_session_raises():
    am = ActiveSessionManager(default_ttl_sec=60)
    br = BotRegistry()
    am.trigger("ob11", "g1", "u1", now_ms=0)
    br.upsert("ob11", "group", "g1", "bot", _FakeTarget(), ts=0)
    with pytest.raises(PushContextError):
        validate_push_context(
            adapter="ob11",
            group_id="g1",
            active_sessions=am,
            bot_registry=br,
            now_ms=999_999,
        )
