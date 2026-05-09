"""ActiveSessionManager 单元测试。"""

from __future__ import annotations

from nonebot_plugin_hermes.core.active_session import ActiveSession, ActiveSessionManager


def test_trigger_creates_session_with_expiry():
    mgr = ActiveSessionManager(default_ttl_sec=60)
    s = mgr.trigger("ob11", "g1", "u42", now_ms=1_000_000)
    assert isinstance(s, ActiveSession)
    assert s.adapter == "ob11"
    assert s.group_id == "g1"
    assert s.triggered_by == "u42"
    assert s.expires_at == 1_000_000 + 60_000


def test_is_active_before_and_after_expiry():
    mgr = ActiveSessionManager(default_ttl_sec=60)
    mgr.trigger("ob11", "g1", "u42", now_ms=0)
    assert mgr.is_active("ob11", "g1", now_ms=30_000) is True
    assert mgr.is_active("ob11", "g1", now_ms=60_001) is False


def test_touch_extends_expiry():
    mgr = ActiveSessionManager(default_ttl_sec=60)
    mgr.trigger("ob11", "g1", "u42", now_ms=0)
    extended = mgr.touch("ob11", "g1", now_ms=30_000)
    assert extended is not None
    assert extended.expires_at == 30_000 + 60_000
    assert mgr.is_active("ob11", "g1", now_ms=80_000) is True


def test_touch_after_expiry_returns_none():
    mgr = ActiveSessionManager(default_ttl_sec=60)
    mgr.trigger("ob11", "g1", "u42", now_ms=0)
    assert mgr.touch("ob11", "g1", now_ms=999_999) is None


def test_end_removes_session():
    mgr = ActiveSessionManager(default_ttl_sec=60)
    mgr.trigger("ob11", "g1", "u42", now_ms=0)
    mgr.end("ob11", "g1")
    assert mgr.get("ob11", "g1") is None
    assert mgr.is_active("ob11", "g1", now_ms=10_000) is False


def test_update_topic_persists():
    mgr = ActiveSessionManager(default_ttl_sec=60)
    mgr.trigger("ob11", "g1", "u42", now_ms=0)
    mgr.update_topic("ob11", "g1", "Rust async")
    assert mgr.get("ob11", "g1").topic_hint == "Rust async"


def test_update_topic_on_missing_session_is_noop():
    mgr = ActiveSessionManager(default_ttl_sec=60)
    mgr.update_topic("ob11", "ghost", "anything")  # 不抛异常
    assert mgr.get("ob11", "ghost") is None


def test_list_filters_by_adapter():
    mgr = ActiveSessionManager(default_ttl_sec=60)
    mgr.trigger("ob11", "g1", "u1", now_ms=0)
    mgr.trigger("kook", "g2", "u2", now_ms=0)
    assert {s.group_id for s in mgr.list()} == {"g1", "g2"}
    assert {s.group_id for s in mgr.list(adapter="ob11")} == {"g1"}


def test_sweep_expired_returns_and_removes():
    mgr = ActiveSessionManager(default_ttl_sec=60)
    mgr.trigger("ob11", "g1", "u1", now_ms=0)  # 60_000 过期
    mgr.trigger("ob11", "g2", "u2", now_ms=10_000)  # 70_000 过期
    expired = mgr.sweep_expired(now_ms=65_000)
    assert {s.group_id for s in expired} == {"g1"}
    assert mgr.get("ob11", "g1") is None
    assert mgr.is_active("ob11", "g2", now_ms=65_000) is True


def test_re_trigger_resets_started_at():
    mgr = ActiveSessionManager(default_ttl_sec=60)
    mgr.trigger("ob11", "g1", "u1", now_ms=0)
    s = mgr.trigger("ob11", "g1", "u2", now_ms=200_000)
    assert s.triggered_by == "u2"
    assert s.started_at == 200_000
    assert s.expires_at == 200_000 + 60_000


def test_ttl_boundary_now_eq_expires_treated_as_expired():
    """TTL 边界一致性测试:三个方法在 now_ms == expires_at 处全部判定为过期。

    防止未来重构(如 ms ↔ s 单位切换)悄悄改成 < 或 >=。
    """
    mgr = ActiveSessionManager(default_ttl_sec=60)
    mgr.trigger("ob11", "g1", "u1", now_ms=0)
    boundary = 60_000  # == expires_at

    assert mgr.is_active("ob11", "g1", now_ms=boundary) is False
    assert mgr.touch("ob11", "g1", now_ms=boundary) is None
    assert mgr.get_if_active("ob11", "g1", now_ms=boundary) is None
    expired = mgr.sweep_expired(now_ms=boundary)
    assert {s.group_id for s in expired} == {"g1"}


def test_get_if_active_filters_expired_silently():
    """get_if_active 必须屏蔽已过期 session,而 get() 仍能看到(供调试)。"""
    mgr = ActiveSessionManager(default_ttl_sec=60)
    mgr.trigger("ob11", "g1", "u1", now_ms=0)
    # 过期但还没 sweep
    assert mgr.get("ob11", "g1") is not None
    assert mgr.get_if_active("ob11", "g1", now_ms=999_999) is None
    # 仍在窗口内
    assert mgr.get_if_active("ob11", "g1", now_ms=30_000) is not None


def test_update_topic_with_none_clears():
    """update_topic(None) 显式清空 topic_hint(话题漂移收尾)。"""
    mgr = ActiveSessionManager(default_ttl_sec=60)
    mgr.trigger("ob11", "g1", "u1", now_ms=0, topic_hint="rust async")
    assert mgr.get("ob11", "g1").topic_hint == "rust async"
    mgr.update_topic("ob11", "g1", None)
    assert mgr.get("ob11", "g1").topic_hint is None
