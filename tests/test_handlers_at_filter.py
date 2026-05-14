"""C 层 @-目标过滤助手单测。

`_msg_at_only_other_users(uni_msg, bot_self_id)` 决定 reactive 入口是否要把
「只 @ 他人未点名 bot」这类消息当成非本路径触发(模式 1 修复)。
"""

from __future__ import annotations


BOT_SELF_ID = "999"


def _make_msg(*segments):
    """延迟到函数内 import,绕开 pytest collection 阶段 alconna 的 plugin loader 钩子。"""
    import nonebot_plugin_alconna as alconna

    return alconna.UniMessage(list(segments))


def _at(target):
    import nonebot_plugin_alconna as alconna

    return alconna.At(flag="user", target=str(target))


def _text(s):
    import nonebot_plugin_alconna as alconna

    return alconna.Text(s)


def test_no_at_segments_returns_false():
    """消息不含任何 @ → 不应该被 C 过滤(仍走原有逻辑)。"""
    from nonebot_plugin_hermes.handlers.message import _msg_at_only_other_users

    msg = _make_msg(_text("hello world"))
    assert _msg_at_only_other_users(msg, BOT_SELF_ID) is False


def test_only_at_other_user_returns_true():
    """消息只 @ 一个非 bot 的用户 → C 命中。"""
    from nonebot_plugin_hermes.handlers.message import _msg_at_only_other_users

    msg = _make_msg(_at("123"), _text(" 你看看"))
    assert _msg_at_only_other_users(msg, BOT_SELF_ID) is True


def test_multiple_at_others_returns_true():
    """消息 @ 多个非 bot 用户 → C 命中。"""
    from nonebot_plugin_hermes.handlers.message import _msg_at_only_other_users

    msg = _make_msg(_at("123"), _at("456"), _text(" 你们怎么看"))
    assert _msg_at_only_other_users(msg, BOT_SELF_ID) is True


def test_at_bot_only_returns_false():
    """消息只 @ bot 自己 → 不命中(走显式触发路径)。"""
    from nonebot_plugin_hermes.handlers.message import _msg_at_only_other_users

    msg = _make_msg(_at(BOT_SELF_ID), _text(" 帮我"))
    assert _msg_at_only_other_users(msg, BOT_SELF_ID) is False


def test_mixed_at_bot_and_other_returns_false():
    """消息混合 @ bot + @ 其他人 → 不命中(bot 在 @ 列表里)。"""
    from nonebot_plugin_hermes.handlers.message import _msg_at_only_other_users

    msg = _make_msg(_at("123"), _at(BOT_SELF_ID), _text(" 大家一起"))
    assert _msg_at_only_other_users(msg, BOT_SELF_ID) is False


def test_bot_self_id_compared_as_string():
    """bot_self_id 与 target 都按字符串比对,防止 int/str 类型不一致导致漏判。"""
    from nonebot_plugin_hermes.handlers.message import _msg_at_only_other_users

    msg = _make_msg(_at("999"), _text("x"))
    assert _msg_at_only_other_users(msg, 999) is False  # type: ignore[arg-type]
