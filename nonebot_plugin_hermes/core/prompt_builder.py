"""Prompt 拼装。

reactive 模式:
- system: runtime_state + decision_protocol(决策契约稳定,利于 prompt cache)
- user: <recent_messages>...<current_message>...,多图时降级为多模态 parts
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .hermes_client import UserContent
from .message_buffer import BufferedMessage


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

    # 字段名与 hermes_client._DECISION_HINT 和 ActiveSessionManager.update_topic 对齐,
    # 模型一次响应里只看到一个字段名 `topic_hint`,避免歧义。
    # `submit_decision` 是契约标识符:M1 路径 B 不真发 tools(P0-spike Hermes 不透传),
    # 但保留这个名字让模型识别"决策上下文",并与 Task 8B 的 structured_tool_name 入参对齐。
    decision_block = (
        "<decision_protocol>\n"
        "你处于群活跃态。每条新消息都需要决定是否要插话。\n"
        "把决策提交为名为 submit_decision 的 JSON 对象,字段:\n"
        "  should_reply (boolean, required) — 是否要回复\n"
        "  reply_text (string) — should_reply=true 时必填,留空表示静默\n"
        "  topic_hint (string) — 简短话题标记(中文 OK),将带入下一轮 runtime_state\n"
        "  should_exit_active (boolean) — 谨慎使用,见下方退出门槛\n"
        "\n"
        "插话原则(决定 should_reply):\n"
        "  - 与你之前的发言或被 @ 的话题强相关 → true\n"
        "  - 有人明显在问你刚说的内容 → true\n"
        "  - 群里闲聊与你无关 → false\n"
        "  - 不确定是否针对你 → false,但保持 should_exit_active=false(沉默观察,不退场)\n"
        "\n"
        "退出门槛(决定 should_exit_active):门槛要高,误判会让你听不到下一句明确请求。\n"
        "只在以下情况设 true:\n"
        "  - 用户明确说再见 / 谢谢够了 / 不用了 / 没问题了\n"
        "  - 你已完成上一次明确请求,且最近一条消息明显跟你无关\n"
        "  - 群里话题完全转向无关内容,且持续超过 3 条\n"
        "其它情况(用户口头思考如「我想想」「让我看看」、犹豫、短停顿、闲聊间歇)\n"
        "一律保持 should_exit_active=false。这些通常是对话中段而非结束。\n"
        "\n"
        "行动诚实(决定 reply_text 内容):\n"
        "  - 如果你的工具/能力可以真去做(查询、搜索、调用外部接口等),先做,\n"
        "    拿到结果后再写 reply_text\n"
        "  - 尝试失败或确实超出你能力时,直接告知失败原因或建议替代:\n"
        "    「我这查不到 X,建议你用 Y」\n"
        "  - 在没有真去做任何尝试时,禁止使用「让我查一下」「稍等」「我去看看」\n"
        "    「这就去办」之类话术——reply_text 发出后就是终态,这种承诺会落空\n"
        "  - 一句话:先行动,后说话;真做不到,直说做不到\n"
        "\n"
        "最终输出必须是 submit_decision 的 JSON 对象,不要在 JSON 外面再包文字。\n"
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
