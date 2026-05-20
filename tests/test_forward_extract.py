"""Unit tests for _extract_forward_full and _summarize_forward helpers.

Deferred-import pattern: alconna and plugin imports are inside test function bodies to
avoid pytest collection-time side effects from alconna's plugin loader hook.
The key ordering rule: always import from nonebot_plugin_hermes BEFORE importing
nonebot_plugin_alconna directly, so the plugin loader has already registered alconna.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_uni_msg(*segments):
    """Build a UniMessage without triggering alconna at collection time."""
    import nonebot_plugin_alconna as alconna

    return alconna.UniMessage(list(segments))


def _make_forward_response(nodes):
    """Build a mock get_forward_msg response dict."""
    return {"messages": nodes}


def _make_node(nickname: str, *text_segs: str, extra_segs=None):
    """Build a OneBot-style forward node dict."""
    message = [{"type": "text", "data": {"text": t}} for t in text_segs]
    if extra_segs:
        message.extend(extra_segs)
    return {"sender": {"nickname": nickname}, "message": message}


# ---------------------------------------------------------------------------
# _extract_forward_full
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_returns_none_when_adapter_not_onebot():
    """Non-OneBot adapters get None immediately; bot.call_api is never called."""
    from nonebot_plugin_hermes.handlers.message import _extract_forward_full
    import nonebot_plugin_alconna as alconna

    bot = MagicMock()
    bot.call_api = AsyncMock()

    msg = _make_uni_msg(alconna.Reference(id="fwd001"))
    result = await _extract_forward_full(msg, bot, adapter_name="telegram")

    assert result is None
    bot.call_api.assert_not_called()


@pytest.mark.asyncio
async def test_extract_returns_none_when_no_reference_segment():
    """UniMessage with only Text has no Reference → None."""
    from nonebot_plugin_hermes.handlers.message import _extract_forward_full
    import nonebot_plugin_alconna as alconna

    bot = MagicMock()
    bot.call_api = AsyncMock()

    msg = _make_uni_msg(alconna.Text("hello"))
    result = await _extract_forward_full(msg, bot, adapter_name="onebotv11")

    assert result is None
    bot.call_api.assert_not_called()


@pytest.mark.asyncio
async def test_extract_normal_5_nodes_within_limits(monkeypatch):
    """5 nodes, max_nodes=10, max_chars=800 → all 5 lines present, no truncation marker."""
    from nonebot_plugin_hermes.handlers.message import _extract_forward_full
    from nonebot_plugin_hermes.config import plugin_config
    import nonebot_plugin_alconna as alconna

    monkeypatch.setattr(plugin_config, "hermes_forward_extract_max_nodes", 10)
    monkeypatch.setattr(plugin_config, "hermes_forward_extract_max_chars", 800)

    nodes = [_make_node(f"User{i}", f"Message content {i}") for i in range(5)]
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=_make_forward_response(nodes))

    msg = _make_uni_msg(alconna.Reference(id="fwd002"))
    result = await _extract_forward_full(msg, bot, adapter_name="onebotv11")

    assert result is not None
    assert 'count="5"' in result
    assert "<forwarded_messages" in result
    assert "</forwarded_messages>" in result
    for i in range(5):
        assert f"Message content {i}" in result
    assert "另有" not in result
    assert "截断" not in result


@pytest.mark.asyncio
async def test_extract_truncates_at_max_nodes(monkeypatch):
    """25 nodes with max_nodes=10 → count=25, 10 content lines, omission marker."""
    from nonebot_plugin_hermes.handlers.message import _extract_forward_full
    from nonebot_plugin_hermes.config import plugin_config
    import nonebot_plugin_alconna as alconna

    monkeypatch.setattr(plugin_config, "hermes_forward_extract_max_nodes", 10)
    monkeypatch.setattr(plugin_config, "hermes_forward_extract_max_chars", 5000)

    nodes = [_make_node(f"User{i}", f"Text {i}") for i in range(25)]
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=_make_forward_response(nodes))

    msg = _make_uni_msg(alconna.Reference(id="fwd003"))
    result = await _extract_forward_full(msg, bot, adapter_name="onebotv11")

    assert result is not None
    assert 'count="25"' in result
    content_lines = [
        ln
        for ln in result.splitlines()
        if ln and not ln.startswith("<forwarded_messages") and not ln.startswith("</forwarded_messages")
    ]
    # 10 content lines + 1 omission marker
    assert len(content_lines) == 11
    assert "[...另有 15 条已省略]" in result


@pytest.mark.asyncio
async def test_extract_truncates_at_max_chars(monkeypatch):
    """10 nodes each with long text, max_chars=200 → char-limit truncation marker."""
    from nonebot_plugin_hermes.handlers.message import _extract_forward_full
    from nonebot_plugin_hermes.config import plugin_config
    import nonebot_plugin_alconna as alconna

    monkeypatch.setattr(plugin_config, "hermes_forward_extract_max_nodes", 50)
    monkeypatch.setattr(plugin_config, "hermes_forward_extract_max_chars", 200)

    long_text = "这是一段非常长的文本内容，专门用来测试字符数上限截断逻辑。" * 3
    nodes = [_make_node(f"UserLong{i}", long_text) for i in range(10)]
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=_make_forward_response(nodes))

    msg = _make_uni_msg(alconna.Reference(id="fwd004"))
    result = await _extract_forward_full(msg, bot, adapter_name="onebotv11")

    assert result is not None
    assert "[...因字符上限截断]" in result
    assert "另有" not in result


@pytest.mark.asyncio
async def test_extract_handles_nested_forward_placeholder(monkeypatch):
    """Node containing a nested forward segment shows placeholder, no recursion."""
    from nonebot_plugin_hermes.handlers.message import _extract_forward_full
    from nonebot_plugin_hermes.config import plugin_config
    import nonebot_plugin_alconna as alconna

    monkeypatch.setattr(plugin_config, "hermes_forward_extract_max_nodes", 10)
    monkeypatch.setattr(plugin_config, "hermes_forward_extract_max_chars", 800)

    nested_fwd_seg = {
        "type": "forward",
        "data": {"id": "nested_id", "content": ["a", "b", "c"]},
    }
    nodes = [
        _make_node("UserA", "Intro text"),
        _make_node("UserB", extra_segs=[nested_fwd_seg]),
    ]
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=_make_forward_response(nodes))

    msg = _make_uni_msg(alconna.Reference(id="fwd005"))
    result = await _extract_forward_full(msg, bot, adapter_name="onebotv11")

    assert result is not None
    assert "[嵌套合并转发 (3 条)]" in result
    # call_api called exactly once (no recursion into nested forward)
    bot.call_api.assert_called_once()


@pytest.mark.asyncio
async def test_extract_returns_fetch_failed_on_api_exception():
    """bot.call_api raises → fetch_failed self-closing tag returned, not None."""
    from nonebot_plugin_hermes.handlers.message import _extract_forward_full
    import nonebot_plugin_alconna as alconna

    bot = MagicMock()
    bot.call_api = AsyncMock(side_effect=RuntimeError("network timeout"))

    msg = _make_uni_msg(alconna.Reference(id="fwd006"))
    result = await _extract_forward_full(msg, bot, adapter_name="onebotv11")

    assert result == '<forwarded_messages count="?" status="fetch_failed"/>'


# ---------------------------------------------------------------------------
# _summarize_forward
# ---------------------------------------------------------------------------


def test_summarize_passes_through_self_closing():
    """Self-closing tags (including fetch_failed) are returned unchanged."""
    from nonebot_plugin_hermes.handlers.message import _summarize_forward

    fetch_failed = '<forwarded_messages count="?" status="fetch_failed"/>'
    assert _summarize_forward(fetch_failed) == fetch_failed

    plain_self_closing = '<forwarded_messages count="3" preview="some text"/>'
    assert _summarize_forward(plain_self_closing) == plain_self_closing


def test_summarize_compresses_multiline_to_preview():
    """Multi-line block with count=5 compresses to single-line self-closing form."""
    import re

    from nonebot_plugin_hermes.handlers.message import _summarize_forward

    block = (
        '<forwarded_messages count="5">\n'
        "Alice: Hello there\n"
        "Bob: How are you\n"
        "Carol: Fine thanks\n"
        "Dave: Great news\n"
        "Eve: See you later\n"
        "</forwarded_messages>"
    )
    result = _summarize_forward(block, max_chars=120)

    assert "\n" not in result
    assert result.endswith("/>")
    assert 'count="5"' in result
    assert 'preview="' in result
    assert len(result) <= 120
    # preview should be non-empty
    preview_match = re.search(r'preview="([^"]*)"', result)
    assert preview_match is not None
    assert len(preview_match.group(1)) > 0


def test_summarize_caps_preview_under_max_chars():
    """Very long content lines: total output length must stay ≤ max_chars."""
    from nonebot_plugin_hermes.handlers.message import _summarize_forward

    long_line = "甲: " + "这是超长文字内容测试用例专用" * 10
    lines = "\n".join(f"User{i}: {long_line}" for i in range(8))
    block = f'<forwarded_messages count="8">\n{lines}\n</forwarded_messages>'

    result = _summarize_forward(block, max_chars=120)

    assert len(result) <= 120
    assert result.endswith("/>")
    assert 'count="8"' in result


# ---------------------------------------------------------------------------
# Fix 1: omitted count accounts for blank (None-returning) nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_omitted_count_accounts_for_blank_nodes(monkeypatch):
    """Blanks at positions 0-2, content at 3-12 (10 nodes), max_nodes=10.

    After consuming the 10th content node the last examined index is 12,
    so omitted = 13 - 13 = 0 → no trailing '另有' line.
    """
    from nonebot_plugin_hermes.handlers.message import _extract_forward_full
    from nonebot_plugin_hermes.config import plugin_config
    import nonebot_plugin_alconna as alconna

    monkeypatch.setattr(plugin_config, "hermes_forward_extract_max_nodes", 10)
    monkeypatch.setattr(plugin_config, "hermes_forward_extract_max_chars", 99999)

    # 3 blank nodes (empty message list) followed by 10 content nodes = 13 total
    blank_node = {"sender": {"nickname": "Ghost"}, "message": []}
    content_nodes = [_make_node(f"User{i}", f"Content {i}") for i in range(10)]
    nodes = [blank_node] * 3 + content_nodes

    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=_make_forward_response(nodes))

    msg = _make_uni_msg(alconna.Reference(id="fwd_blank"))
    result = await _extract_forward_full(msg, bot, adapter_name="onebotv11")

    assert result is not None
    assert 'count="13"' in result
    content_lines = [
        ln
        for ln in result.splitlines()
        if ln and not ln.startswith("<forwarded_messages") and not ln.startswith("</forwarded_messages")
    ]
    assert len(content_lines) == 10
    assert "另有" not in result


@pytest.mark.asyncio
async def test_extract_omitted_count_correct_without_blanks(monkeypatch):
    """25 all-content nodes, max_nodes=10 → omitted = 15 (regression guard)."""
    from nonebot_plugin_hermes.handlers.message import _extract_forward_full
    from nonebot_plugin_hermes.config import plugin_config
    import nonebot_plugin_alconna as alconna

    monkeypatch.setattr(plugin_config, "hermes_forward_extract_max_nodes", 10)
    monkeypatch.setattr(plugin_config, "hermes_forward_extract_max_chars", 99999)

    nodes = [_make_node(f"U{i}", f"Msg {i}") for i in range(25)]
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=_make_forward_response(nodes))

    msg = _make_uni_msg(alconna.Reference(id="fwd_omit15"))
    result = await _extract_forward_full(msg, bot, adapter_name="onebotv11")

    assert result is not None
    assert 'count="25"' in result
    assert "[...另有 15 条已省略]" in result


# ---------------------------------------------------------------------------
# Fix 3: HTML escaping in preview attribute
# ---------------------------------------------------------------------------


def test_summarize_escapes_special_chars_in_preview():
    """Node line containing <img>, \"quoted\", and a & b are escaped in preview."""
    from nonebot_plugin_hermes.handlers.message import _summarize_forward

    # Build a block where one inner line contains all three special patterns.
    # Keep it ≤ 30 chars so it is not truncated by the 30-char compress step.
    inner_line = 'A: <x> & "q"'
    block = f'<forwarded_messages count="1">\n{inner_line}\n</forwarded_messages>'

    result = _summarize_forward(block, max_chars=300)

    # Must be a valid single-line self-closing tag
    assert "\n" not in result
    assert result.endswith("/>")

    # Extract the preview attribute value (between preview=" and the closing ")
    import re

    m = re.search(r'preview="([^"]*)"', result)
    assert m is not None, f"No preview attribute found in: {result}"
    preview_val = m.group(1)

    # Escaped forms must be present
    assert "&lt;" in preview_val
    assert "&gt;" in preview_val
    assert "&amp;" in preview_val

    # Raw hazardous chars must NOT appear inside the preview value
    assert "<" not in preview_val
    assert ">" not in preview_val
    assert '"' not in preview_val


# ---------------------------------------------------------------------------
# Fix 4: self-closing regex requires at least one attribute char ([^>]+)
# ---------------------------------------------------------------------------


def test_summarize_does_not_treat_empty_attr_tag_as_self_closing():
    """<forwarded_messages /> (no attributes) must not be passed through as self-closing."""
    from nonebot_plugin_hermes.handlers.message import _summarize_forward

    # This is a malformed/empty tag — the tightened regex [^>]+ requires ≥1 attr char.
    malformed = "<forwarded_messages />"
    result = _summarize_forward(malformed)

    # It should NOT be returned unchanged (it's not a valid self-closing summary tag)
    assert result != malformed
