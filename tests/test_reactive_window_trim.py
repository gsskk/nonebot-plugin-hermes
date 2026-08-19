"""reactive 续发轮窗口裁剪:select_followup_window 纯函数 + handler 接线。"""

from __future__ import annotations

from nonebot_plugin_hermes.core.message_buffer import BufferedMessage
from nonebot_plugin_hermes.core.prompt_builder import select_followup_window


def _msg(ts: int, content: str, *, is_bot: bool = False, msg_id: int | None = None) -> BufferedMessage:
    return BufferedMessage(
        ts=ts,
        adapter="ob11",
        group_id="g1",
        user_id="u9" if is_bot else "u1",
        nickname="assistant" if is_bot else "member",
        content=content,
        is_bot=is_bot,
        id=msg_id,
    )


def _window(n: int, bot_at: int | None = None) -> list[BufferedMessage]:
    """构造 n 条新→旧消息;bot_at 指定第几条(0=最新)是 bot 发言。"""
    return [_msg(ts=1000 - i, content=f"m{i}", is_bot=(i == bot_at), msg_id=100 - i) for i in range(n)]


def test_limit_ge_len_returns_all():
    recent = _window(4)
    assert select_followup_window(recent, 4) == recent
    assert select_followup_window(recent, 10) == recent


def test_limit_zero_or_negative_disables_trim():
    recent = _window(6)
    assert select_followup_window(recent, 0) == recent
    assert select_followup_window(recent, -1) == recent


def test_basic_trim_keeps_newest():
    recent = _window(6)
    assert select_followup_window(recent, 3) == recent[:3]


def test_bot_line_inside_tail_not_duplicated():
    recent = _window(6, bot_at=1)
    result = select_followup_window(recent, 3)
    assert result == recent[:3]


def test_bot_line_outside_tail_is_pinned_after():
    recent = _window(6, bot_at=4)
    result = select_followup_window(recent, 3)
    assert result == recent[:3] + [recent[4]]


def test_no_bot_line_just_tail():
    recent = _window(6)
    assert select_followup_window(recent, 2) == recent[:2]


def test_multiple_bot_lines_pins_only_newest():
    recent = _window(8, bot_at=5)
    recent[6] = _msg(ts=994, content="m6", is_bot=True, msg_id=94)
    result = select_followup_window(recent, 3)
    assert result == recent[:3] + [recent[5]]


def test_empty_input():
    assert select_followup_window([], 3) == []
