"""prompt_builder 单元测试。"""

from __future__ import annotations

from nonebot_plugin_hermes.core.message_buffer import BufferedMessage
from nonebot_plugin_hermes.core.prompt_builder import (
    build_reactive_system_prompt,
    build_reactive_user_content,
)


def _msg(ts, sender="alice", content="hello", imgs=None, is_bot=False):
    return BufferedMessage(
        ts=ts,
        adapter="ob11",
        group_id="g1",
        user_id=sender,
        nickname=sender,
        content=content,
        image_urls=imgs or [],
        reply_to_ts=None,
        is_bot=is_bot,
    )


def test_system_prompt_includes_runtime_state_and_decision_protocol():
    sp = build_reactive_system_prompt(
        adapter="ob11",
        group_id="g1",
        triggered_by="u42",
        triggered_by_nickname="老张",
        topic_hint="Rust async runtime",
    )
    assert "<runtime_state>" in sp
    assert "adapter: ob11" in sp
    assert "group_id: g1" in sp
    assert "triggered_by: u42 (老张)" in sp
    assert "Rust async runtime" in sp
    assert "<decision_protocol>" in sp
    assert "submit_decision" in sp


def test_system_prompt_omits_topic_when_none():
    sp = build_reactive_system_prompt(
        adapter="ob11",
        group_id="g1",
        triggered_by="u42",
        triggered_by_nickname=None,
        topic_hint=None,
    )
    assert "topic_hint:" not in sp


def test_user_content_text_only_when_no_images():
    msgs = [_msg(100, "alice", "hi"), _msg(200, "bob", "hello")]
    content = build_reactive_user_content(
        recent_messages=msgs,
        current_user_id="charlie",
        current_nickname="Charlie",
        current_text="how is it going?",
        current_image_urls=[],
    )
    assert isinstance(content, str)
    assert "<recent_messages>" in content
    assert "alice: hi" in content
    assert "bob: hello" in content
    assert "<current_message>" in content
    assert "Charlie: how is it going?" in content


def test_user_content_multimodal_when_images_present():
    msgs = [_msg(100, "alice", "hi", imgs=["http://x/a.png"])]
    content = build_reactive_user_content(
        recent_messages=msgs,
        current_user_id="charlie",
        current_nickname="Charlie",
        current_text="see this",
        current_image_urls=["http://y/b.png"],
    )
    assert isinstance(content, list)
    types = [p.get("type") for p in content]
    assert "text" in types
    assert "image_url" in types
    # 当前图必须是最后一个 image_url(LLM 才知道用户问的是它)
    last_img = next((p for p in reversed(content) if p.get("type") == "image_url"), None)
    assert last_img is not None
    assert last_img["image_url"]["url"] == "http://y/b.png"


def test_user_content_marks_bot_messages():
    msgs = [_msg(100, "alice", "hi"), _msg(200, "bot", "hi alice", is_bot=True)]
    content = build_reactive_user_content(
        recent_messages=msgs,
        current_user_id="charlie",
        current_nickname="Charlie",
        current_text="?",
        current_image_urls=[],
    )
    assert isinstance(content, str)
    assert "[bot] bot: hi alice" in content
