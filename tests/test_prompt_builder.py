"""prompt_builder 单元测试。"""

from __future__ import annotations

from nonebot_plugin_hermes.core.message_buffer import BufferedMessage
from nonebot_plugin_hermes.core.prompt_builder import (
    build_passive_system_prompt,
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
    """topic_hint=None 时 runtime_state 不出现 topic_hint 行。

    注:本测试从 spec 故意偏离。spec 原 assertion `"topic_hint:" not in sp`
    会误伤 decision_protocol 里 'topic_hint (string)' 这条字段说明
    (模型必须知道字段名,不能删)。正确不变量是:topic_hint 不应出现在
    runtime_state 段。原 spec 写得过宽,此处缩到正确范围。"""
    sp = build_reactive_system_prompt(
        adapter="ob11",
        group_id="g1",
        triggered_by="u42",
        triggered_by_nickname=None,
        topic_hint=None,
    )
    runtime_state = sp.split("</runtime_state>")[0]
    assert "topic_hint:" not in runtime_state


def test_decision_protocol_uses_topic_hint_field_name():
    """字段名必须是 topic_hint(对齐 hermes_client _DECISION_HINT 与
    ActiveSessionManager.update_topic),不能是 topic_tag 等别名,否则模型
    输出哪个字段都成,parse 出来 active session 拿不到 hint。"""
    sp = build_reactive_system_prompt(
        adapter="ob11",
        group_id="g1",
        triggered_by="u42",
        triggered_by_nickname=None,
        topic_hint=None,
    )
    decision = sp.split("<decision_protocol>")[1]
    assert "topic_hint" in decision
    assert "topic_tag" not in decision


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
    # 第一个 part 必须是 text,且包含 history + current_message 两个块
    assert content[0]["type"] == "text"
    assert "<recent_messages>" in content[0]["text"]
    assert "<current_message>" in content[0]["text"]
    assert "Charlie: see this" in content[0]["text"]
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


def test_user_content_empty_history_still_produces_block():
    """recent_messages=[] 时 <recent_messages> 块仍存在(空但格式齐全),
    避免下游 prompt 解析(如未来 prompt cache key 计算)误判。"""
    content = build_reactive_user_content(
        recent_messages=[],
        current_user_id="alice",
        current_nickname="Alice",
        current_text="hi",
        current_image_urls=[],
    )
    assert "<recent_messages>" in content
    assert "</recent_messages>" in content
    assert "Alice: hi" in content


def test_passive_prompt_group_with_history_appends_recent_messages_block():
    """群聊 + 有 buffer 历史:Message Context 后追加 <recent_messages> 块,
    历史按旧→新顺序;bot 自己的回复带 [bot] 前缀。这是 0.2 补回 0.1.6
    群聊旁观历史注入的核心场景。"""
    msgs = [_msg(200, "bob", "hi all"), _msg(100, "alice", "hello")]  # 新→旧 入参
    sp = build_passive_system_prompt(
        adapter="ob11",
        is_private=False,
        user_id="charlie",
        group_id="g1",
        recent_messages=msgs,
    )
    assert "Platform: ob11" in sp
    assert "Chat Type: Group" in sp
    assert "User ID: charlie" in sp
    assert "Group ID: g1" in sp
    assert "<recent_messages>" in sp
    assert "</recent_messages>" in sp
    # 旧→新 顺序:alice 行必须出现在 bob 行之前
    alice_idx = sp.index("alice: hello")
    bob_idx = sp.index("bob: hi all")
    assert alice_idx < bob_idx


def test_passive_prompt_marks_bot_messages():
    msgs = [_msg(100, "alice", "hi"), _msg(200, "bot", "hi alice", is_bot=True)]
    sp = build_passive_system_prompt(
        adapter="ob11",
        is_private=False,
        user_id="charlie",
        group_id="g1",
        recent_messages=msgs,
    )
    assert "[bot] bot: hi alice" in sp


def test_passive_prompt_empty_history_omits_block():
    """recent_messages=[] 时不追加 <recent_messages> 块——passive 路径下
    塞个空块只会让 prompt 变长却没信息;与 reactive 的「保持格式齐全」诉求不同。"""
    sp = build_passive_system_prompt(
        adapter="ob11",
        is_private=False,
        user_id="charlie",
        group_id="g1",
        recent_messages=[],
    )
    assert "<recent_messages>" not in sp
    assert "Group ID: g1" in sp


def test_passive_prompt_private_omits_group_id():
    """私聊场景调用方一般不会传 history,但若误传也别在 prompt 里漏出
    Group ID 字段——和 hermes_client 默认拼装行为对齐。"""
    sp = build_passive_system_prompt(
        adapter="ob11",
        is_private=True,
        user_id="charlie",
        group_id=None,
        recent_messages=[],
    )
    assert "Chat Type: Private" in sp
    assert "Group ID" not in sp


def test_user_content_empty_current_text_with_image_is_valid():
    """图片消息无文字描述(用户只发图)是常见场景,空 current_text + 图片应正确产出
    多模态 parts。"""
    content = build_reactive_user_content(
        recent_messages=[],
        current_user_id="alice",
        current_nickname="Alice",
        current_text="",
        current_image_urls=["http://x/photo.jpg"],
    )
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert "Alice:" in content[0]["text"]  # speaker 仍存在,内容空
    assert content[-1]["type"] == "image_url"
    assert content[-1]["image_url"]["url"] == "http://x/photo.jpg"
