"""MessageBuffer 单元测试。"""

from __future__ import annotations

from typing import Optional

import pytest

from nonebot_plugin_hermes.core.message_buffer import (
    BufferedMessage,
    MessageBuffer,
    is_private_key,
)


def _msg(
    ts: int,
    group: Optional[str] = "g1",
    user: str = "u1",
    content: str = "hi",
) -> BufferedMessage:
    return BufferedMessage(
        ts=ts,
        adapter="ob11",
        group_id=group,
        user_id=user,
        nickname=user,
        content=content,
        image_urls=[],
        reply_to_ts=None,
        is_bot=False,
    )


def test_append_and_get_recent_returns_newest_first():
    buf = MessageBuffer(per_group_cap=10, total_groups_cap=10)
    for ts in (100, 200, 300):
        buf.append(_msg(ts))

    recent = buf.get_recent("ob11", "g1", limit=10)
    assert [m.ts for m in recent] == [300, 200, 100]


def test_per_group_cap_evicts_oldest():
    buf = MessageBuffer(per_group_cap=3, total_groups_cap=10)
    for ts in range(1, 6):
        buf.append(_msg(ts))

    recent = buf.get_recent("ob11", "g1", limit=10)
    assert [m.ts for m in recent] == [5, 4, 3]


def test_total_groups_cap_evicts_lru_group():
    buf = MessageBuffer(per_group_cap=10, total_groups_cap=2)
    buf.append(_msg(100, group="A"))
    buf.append(_msg(200, group="B"))
    buf.append(_msg(300, group="A"))  # 触碰 A,B 变成 LRU
    buf.append(_msg(400, group="C"))  # 应淘汰 B

    assert buf.get_recent("ob11", "B", limit=10) == []
    assert len(buf.get_recent("ob11", "A", limit=10)) == 2
    assert len(buf.get_recent("ob11", "C", limit=10)) == 1


def test_read_promotes_lru_protects_against_eviction():
    """有意行为:get_recent 也 move_to_end,被读的群不应被淘汰。"""
    buf = MessageBuffer(per_group_cap=10, total_groups_cap=2)
    buf.append(_msg(100, group="A"))
    buf.append(_msg(200, group="B"))
    # A 是 LRU 候选;读它一下把它推到 MRU
    _ = buf.get_recent("ob11", "A", limit=10)
    # 现在写入 C,应当淘汰 B(读 A 后 B 才是 LRU)
    buf.append(_msg(300, group="C"))

    assert buf.get_recent("ob11", "B", limit=10) == []
    assert len(buf.get_recent("ob11", "A", limit=10)) == 1
    assert len(buf.get_recent("ob11", "C", limit=10)) == 1


def test_get_recent_with_before_ts_filter():
    buf = MessageBuffer(per_group_cap=10, total_groups_cap=10)
    for ts in (100, 200, 300, 400):
        buf.append(_msg(ts))

    recent = buf.get_recent("ob11", "g1", limit=10, before_ts=300)
    assert [m.ts for m in recent] == [200, 100]


def test_get_recent_unknown_group_returns_empty():
    buf = MessageBuffer(per_group_cap=10, total_groups_cap=10)
    assert buf.get_recent("ob11", "ghost", limit=10) == []


def test_known_groups_excludes_evicted():
    buf = MessageBuffer(per_group_cap=10, total_groups_cap=2)
    buf.append(_msg(100, group="A"))
    buf.append(_msg(200, group="B"))
    buf.append(_msg(300, group="C"))  # 淘汰 A

    known = set(buf.known_groups())
    assert ("ob11", "B") in known
    assert ("ob11", "C") in known
    assert ("ob11", "A") not in known


def test_private_message_uses_user_as_group_key():
    buf = MessageBuffer(per_group_cap=10, total_groups_cap=10)
    buf.append(_msg(100, group=None, user="alice"))
    # 私聊也能取回
    recent = buf.get_recent("ob11", None, limit=10, owner_user_id="alice")
    assert len(recent) == 1


def test_get_recent_private_without_owner_raises():
    """守卫:私聊查询忘传 owner_user_id 必须早爆,不能静默返空。"""
    buf = MessageBuffer(per_group_cap=10, total_groups_cap=10)
    with pytest.raises(ValueError, match="owner_user_id is required"):
        buf.get_recent("ob11", None, limit=10)


def test_is_private_key_helper():
    """is_private_key 帮助消费者(Task 13/15)区分群桶 / 私聊桶,无需 string-match。"""
    buf = MessageBuffer(per_group_cap=10, total_groups_cap=10)
    buf.append(_msg(100, group="g1"))
    buf.append(_msg(200, group=None, user="alice"))

    keys = buf.known_groups()
    assert sum(1 for k in keys if is_private_key(k)) == 1
    assert sum(1 for k in keys if not is_private_key(k)) == 1


def test_limit_respected():
    buf = MessageBuffer(per_group_cap=100, total_groups_cap=10)
    for ts in range(1, 21):
        buf.append(_msg(ts))
    recent = buf.get_recent("ob11", "g1", limit=5)
    assert len(recent) == 5
    assert recent[0].ts == 20
