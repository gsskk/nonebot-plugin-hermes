"""Prompt 拼装。

reactive 模式:
- system: runtime_state + decision_protocol(决策契约稳定,利于 prompt cache)
- user: <recent_messages>...<current_message>...,多图时降级为多模态 parts
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union

from .message_buffer import BufferedMessage

UserContent = Union[str, List[Dict[str, Any]]]


def build_reactive_system_prompt(
    *,
    adapter: str,
    group_id: str,
    triggered_by: str,
    triggered_by_nickname: Optional[str],
    topic_hint: Optional[str],
) -> str:
    nick = f" ({triggered_by_nickname})" if triggered_by_nickname else ""
    runtime_lines = [
        "<runtime_state>",
        "mode: reactive",
        f"adapter: {adapter}",
        f"group_id: {group_id}",
        f"triggered_by: {triggered_by}{nick}",
    ]
    if topic_hint:
        runtime_lines.append(f"topic_hint: {topic_hint}")
    runtime_lines.append("</runtime_state>")

    decision_block = (
        "<decision_protocol>\n"
        "你处于群活跃态。每条新消息都需要决定是否要插话。\n"
        "你的输出必须是对 submit_decision 工具的调用,字段:\n"
        "  should_reply: bool — 是否要回复\n"
        "  reply_text: str — should_reply=true 时必填,留空表示静默\n"
        "  topic_tag: str — 简短话题标记(中文 OK),将作为 topic_hint 传入下一轮\n"
        "  should_exit_active: bool — 话题已结束时设 true\n"
        "插话原则:\n"
        "  - 与你之前的发言或被 @ 的话题强相关 → reply\n"
        "  - 群里在闲聊与你无关 → should_reply=false\n"
        "  - 有人明显在问你刚说的内容 → reply\n"
        "不要在工具调用之外输出文本。\n"
        "</decision_protocol>"
    )
    return "\n".join(runtime_lines) + "\n\n" + decision_block


def build_reactive_user_content(
    *,
    recent_messages: Sequence[BufferedMessage],
    current_user_id: str,
    current_nickname: Optional[str],
    current_text: str,
    current_image_urls: Sequence[str],
) -> UserContent:
    """recent_messages: 新→旧顺序;在 prompt 内反转为旧→新。"""
    history_lines = ["<recent_messages>"]
    for m in reversed(list(recent_messages)):
        prefix = "[bot] " if m.is_bot else ""
        speaker = m.nickname or m.user_id
        line = f"{prefix}{speaker}: {m.content}"
        history_lines.append(line)
    history_lines.append("</recent_messages>")

    current_speaker = current_nickname or current_user_id
    current_block_text = f"<current_message>\n{current_speaker}: {current_text}\n</current_message>"

    text_block = "\n".join(history_lines) + "\n\n" + current_block_text

    if not current_image_urls:
        return text_block

    parts: List[Dict[str, Any]] = [{"type": "text", "text": text_block}]
    for u in current_image_urls:
        parts.append({"type": "image_url", "image_url": {"url": u}})
    return parts
