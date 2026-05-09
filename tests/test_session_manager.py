"""SessionManager 单元测试。

精简后的 SessionManager 只负责 session key 生成与 generation 递增。
历史缓冲(record_history / get_history_context)已迁移 MessageBuffer。
"""

from __future__ import annotations

from nonebot_plugin_hermes.core.session import SessionManager


def test_get_session_key_group_unique_per_user():
    sm = SessionManager()
    k1 = sm.get_session_key("ob11", False, "u1", "g1")
    k2 = sm.get_session_key("ob11", False, "u2", "g1")
    assert k1 != k2
    assert k1 == "hermes-ob11+group+g1+u1"
    assert k2 == "hermes-ob11+group+g1+u2"


def test_get_session_key_private_format():
    sm = SessionManager()
    assert sm.get_session_key("ob11", True, "u1") == "hermes-ob11+private+u1"


def test_get_session_key_idempotent():
    sm = SessionManager()
    k1 = sm.get_session_key("ob11", False, "u1", "g1")
    k2 = sm.get_session_key("ob11", False, "u1", "g1")
    assert k1 == k2


def test_clear_session_increments_generation():
    sm = SessionManager()
    k0 = sm.get_session_key("ob11", False, "u1", "g1")
    assert k0 == "hermes-ob11+group+g1+u1"

    sm.clear_session("ob11", False, "u1", "g1")
    k1 = sm.get_session_key("ob11", False, "u1", "g1")
    assert k1 == "hermes-ob11+group+g1+u1-g1"

    sm.clear_session("ob11", False, "u1", "g1")
    k2 = sm.get_session_key("ob11", False, "u1", "g1")
    assert k2 == "hermes-ob11+group+g1+u1-g2"


def test_clear_session_does_not_affect_other_keys():
    sm = SessionManager()
    sm.get_session_key("ob11", False, "u1", "g1")
    sm.get_session_key("ob11", False, "u2", "g1")
    sm.clear_session("ob11", False, "u1", "g1")

    # u1 has new generation; u2 unchanged
    assert sm.get_session_key("ob11", False, "u1", "g1") == "hermes-ob11+group+g1+u1-g1"
    assert sm.get_session_key("ob11", False, "u2", "g1") == "hermes-ob11+group+g1+u2"
