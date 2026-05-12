"""InflightRegistry 单元测试。"""

from __future__ import annotations


from nonebot_plugin_hermes.core.inflight import InflightRegistry, MAX_REFIRE_DEPTH
from nonebot_plugin_hermes.core.message_buffer import BufferedMessage


def _msg(ts: int, user: str = "u1", content: str = "hi") -> BufferedMessage:
    return BufferedMessage(
        ts=ts,
        adapter="ob11",
        group_id="g1",
        user_id=user,
        nickname=user,
        content=content,
        image_urls=[],
        reply_to_ts=None,
        is_bot=False,
    )


def test_try_enter_on_empty_returns_entered():
    reg = InflightRegistry()
    result = reg.try_enter(("ob11", "group:g1"), _msg(100), now_ms=100)
    assert result == "entered"
    assert reg.take_pending(("ob11", "group:g1")) is None
    reg.exit(("ob11", "group:g1"))


def test_second_try_enter_returns_pending_set():
    reg = InflightRegistry()
    reg.try_enter(("ob11", "group:g1"), _msg(100), now_ms=100)
    result = reg.try_enter(("ob11", "group:g1"), _msg(200), now_ms=200)
    assert result == "pending_set"
    pending = reg.take_pending(("ob11", "group:g1"))
    assert pending is not None and pending.ts == 200
    reg.exit(("ob11", "group:g1"))


def test_take_pending_is_destructive():
    reg = InflightRegistry()
    reg.try_enter(("ob11", "group:g1"), _msg(100), now_ms=100)
    reg.try_enter(("ob11", "group:g1"), _msg(200), now_ms=200)
    reg.take_pending(("ob11", "group:g1"))
    assert reg.take_pending(("ob11", "group:g1")) is None
    reg.exit(("ob11", "group:g1"))


def test_exit_releases_slot_for_reentry():
    reg = InflightRegistry()
    reg.try_enter(("ob11", "group:g1"), _msg(100), now_ms=100)
    reg.exit(("ob11", "group:g1"))
    result = reg.try_enter(("ob11", "group:g1"), _msg(200), now_ms=200)
    assert result == "entered"
    reg.exit(("ob11", "group:g1"))


def test_pending_overwritten_by_later_msg():
    reg = InflightRegistry()
    reg.try_enter(("ob11", "group:g1"), _msg(100), now_ms=100)
    reg.try_enter(("ob11", "group:g1"), _msg(200, content="first"), now_ms=200)
    reg.try_enter(("ob11", "group:g1"), _msg(300, content="latest"), now_ms=300)
    pending = reg.take_pending(("ob11", "group:g1"))
    assert pending is not None and pending.content == "latest"
    reg.exit(("ob11", "group:g1"))


def test_different_keys_independent():
    reg = InflightRegistry()
    assert reg.try_enter(("ob11", "group:g1"), _msg(100), now_ms=100) == "entered"
    assert reg.try_enter(("ob11", "group:g2"), _msg(110), now_ms=110) == "entered"
    assert reg.try_enter(("ob11", "private:u1"), _msg(120), now_ms=120) == "entered"
    reg.exit(("ob11", "group:g1"))
    reg.exit(("ob11", "group:g2"))
    reg.exit(("ob11", "private:u1"))


def test_max_refire_depth_constant_is_3():
    assert MAX_REFIRE_DEPTH == 3


def test_take_pending_on_missing_slot_returns_none():
    reg = InflightRegistry()
    assert reg.take_pending(("ob11", "group:nonexistent")) is None


def test_exit_on_missing_slot_is_noop():
    reg = InflightRegistry()
    reg.exit(("ob11", "group:nonexistent"))
