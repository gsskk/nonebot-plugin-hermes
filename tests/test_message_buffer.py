"""MessageBuffer 单元测试。"""

from __future__ import annotations


from nonebot_plugin_hermes.core.message_buffer import BufferedMessage, MessageBuffer


def _msg(ts: int, group: str = "g1", user: str = "u1", content: str = "hi") -> BufferedMessage:
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
    msg = _msg(100, group=None, user="alice")  # type: ignore[arg-type]
    msg.group_id = None
    buf.append(msg)
    # 私聊也能取回
    recent = buf.get_recent("ob11", None, limit=10, owner_user_id="alice")
    assert len(recent) == 1


def test_limit_respected():
    buf = MessageBuffer(per_group_cap=100, total_groups_cap=10)
    for ts in range(1, 21):
        buf.append(_msg(ts))
    recent = buf.get_recent("ob11", "g1", limit=5)
    assert len(recent) == 5
    assert recent[0].ts == 20
