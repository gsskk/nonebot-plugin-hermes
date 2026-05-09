"""HermesClient 结构化输出测试(路径 B)。"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pytest import MonkeyPatch

from nonebot_plugin_hermes.core.hermes_client import (
    HermesClient,
    extract_response_media,
)


class _MockResponse:
    def __init__(self, status_code: int, body: dict[str, Any]):
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body)

    def json(self) -> dict[str, Any]:
        return self._body


class _MockClient:
    def __init__(self, *, response: _MockResponse) -> None:
        self._response = response
        self.last_payload: dict[str, Any] | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def post(self, url, *, json, headers):
        self.last_payload = json
        return self._response


def _patch_httpx(monkeypatch: MonkeyPatch, response: _MockResponse) -> _MockClient:
    client = _MockClient(response=response)

    def factory(*args: Any, **kwargs: Any) -> _MockClient:
        return client

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return client


@pytest.mark.asyncio
async def test_path_b_extracts_first_json5_block(monkeypatch: MonkeyPatch):
    body = {
        "choices": [
            {
                "message": {
                    "content": (
                        "好的,这是我的决策:\n"
                        "{ should_reply: true, reply_text: '收到', topic_hint: 'greeting' }\n"
                        "(说明:简单问候)"
                    )
                }
            }
        ]
    }
    _patch_httpx(monkeypatch, _MockResponse(200, body))

    client = HermesClient()
    r = await client.chat(
        text="hi",
        session_key="s1",
        user_id="u1",
        group_id="g1",
        adapter_name="ob11",
        is_private=False,
        mode="reactive",
        expect_structured=True,
        structured_tool_name="submit_decision",
    )
    assert r.parse_failed is False
    assert r.structured == {"should_reply": True, "reply_text": "收到", "topic_hint": "greeting"}


@pytest.mark.asyncio
async def test_path_b_no_json_block_marks_parse_failed(monkeypatch: MonkeyPatch):
    body = {"choices": [{"message": {"content": "我无法生成 JSON。"}}]}
    _patch_httpx(monkeypatch, _MockResponse(200, body))
    client = HermesClient()
    r = await client.chat(
        text="hi",
        session_key="s1",
        user_id="u1",
        group_id="g1",
        adapter_name="ob11",
        is_private=False,
        mode="reactive",
        expect_structured=True,
        structured_tool_name="submit_decision",
    )
    assert r.parse_failed is True
    # raw_text 必须保留,handler 据此降级展示 / 记日志
    assert r.raw_text == "我无法生成 JSON。"
    assert r.is_transport_error is False


@pytest.mark.asyncio
async def test_path_b_passive_mode_returns_raw_text(monkeypatch: MonkeyPatch):
    """passive 模式:expect_structured=False,直接返 raw_text 不解析。"""
    body = {"choices": [{"message": {"role": "assistant", "content": "raw fallback message"}}]}
    _patch_httpx(monkeypatch, _MockResponse(200, body))

    client = HermesClient()
    result = await client.chat(
        text="hi",
        session_key="s1",
        user_id="u1",
        adapter_name="ob11",
        is_private=True,
        group_id=None,
        mode="passive",
        expect_structured=False,
    )
    assert result.parse_failed is False
    assert result.raw_text == "raw fallback message"
    assert result.structured is None


def test_extract_response_media_strips_md_and_media_tags():
    text = "hello ![a](http://x/y.png) MEDIA:http://x/z.mp4 world"
    cleaned, urls = extract_response_media(text)
    assert "http://x/y.png" in urls
    assert "http://x/z.mp4" in urls
    assert "![a]" not in cleaned
    assert "MEDIA:" not in cleaned


@pytest.mark.asyncio
async def test_path_b_appends_decision_hint_to_system_prompt(monkeypatch: MonkeyPatch):
    """expect_structured=True 时,system prompt 必须含 STRUCTURED OUTPUT 段。"""
    body = {"choices": [{"message": {"content": '{"should_reply": false}'}}]}
    mock = _patch_httpx(monkeypatch, _MockResponse(200, body))

    client = HermesClient()
    await client.chat(
        text="hi",
        session_key="s1",
        user_id="u1",
        group_id="g1",
        adapter_name="ob11",
        is_private=False,
        mode="reactive",
        expect_structured=True,
        structured_tool_name="submit_decision",
    )
    payload = mock.last_payload
    assert payload is not None
    assert "tools" not in payload  # 路径 B 不发 tools
    assert "tool_choice" not in payload
    sys_msg = payload["messages"][0]["content"]
    assert "STRUCTURED OUTPUT" in sys_msg
    assert "should_reply" in sys_msg


@pytest.mark.asyncio
async def test_http_error_marks_transport_and_parse_failed(monkeypatch: MonkeyPatch):
    """HTTP 500 必须同时标 parse_failed=True 与 is_transport_error=True,
    供 Task 15 handler 区分"重试 vs 降级"。"""
    _patch_httpx(monkeypatch, _MockResponse(500, {"error": "server down"}))

    client = HermesClient()
    r = await client.chat(
        text="hi",
        session_key="s1",
        user_id="u1",
        group_id="g1",
        adapter_name="ob11",
        is_private=False,
        mode="reactive",
        expect_structured=True,
        structured_tool_name="submit_decision",
    )
    assert r.parse_failed is True
    assert r.is_transport_error is True
    assert "500" in r.raw_text


@pytest.mark.asyncio
async def test_empty_choices_with_expect_structured_marks_parse_failed(monkeypatch: MonkeyPatch):
    """期望结构化但 choices=[] 是结构性失败,而非"模型选择不回"。"""
    _patch_httpx(monkeypatch, _MockResponse(200, {"choices": []}))

    client = HermesClient()
    r = await client.chat(
        text="hi",
        session_key="s1",
        user_id="u1",
        group_id="g1",
        adapter_name="ob11",
        is_private=False,
        mode="reactive",
        expect_structured=True,
        structured_tool_name="submit_decision",
    )
    assert r.parse_failed is True
    # 但不是 transport 错(HTTP 200,只是响应 body 为空 choices)
    assert r.is_transport_error is False


@pytest.mark.asyncio
async def test_user_content_override_replaces_text_and_image_urls(monkeypatch: MonkeyPatch):
    """prompt_builder 给 user_content_override 时,text/image_urls 应被忽略。"""
    body = {"choices": [{"message": {"content": "ok"}}]}
    mock = _patch_httpx(monkeypatch, _MockResponse(200, body))

    custom_content = [
        {"type": "text", "text": "<<HEAD>>"},
        {"type": "image_url", "image_url": {"url": "http://x/a.jpg"}},
    ]
    client = HermesClient()
    await client.chat(
        text="ignored",
        image_urls=["http://ignored.png"],
        session_key="s1",
        user_id="u1",
        group_id="g1",
        adapter_name="ob11",
        is_private=False,
        user_content_override=custom_content,
    )
    sent = mock.last_payload["messages"][1]["content"]
    assert sent == custom_content
    assert "ignored" not in str(sent)


def test_decision_hint_field_names_are_canonical():
    """_DECISION_HINT 必须用 canonical 字段名(should_reply/reply_text/topic_hint/
    should_exit_active),与 prompt_builder 的 decision_protocol 同口径。任何字段
    drift(如 topic_tag、shouldReply 驼峰)都应被这个测试拦下。"""
    from nonebot_plugin_hermes.core.hermes_client import _DECISION_HINT

    assert "should_reply" in _DECISION_HINT
    assert "reply_text" in _DECISION_HINT
    assert "topic_hint" in _DECISION_HINT
    assert "should_exit_active" in _DECISION_HINT
    # 反例:防 drift
    assert "topic_tag" not in _DECISION_HINT
    assert "shouldReply" not in _DECISION_HINT  # camelCase 漂移


# --- maybe_extract_decision_reply_text (passive defensive parse) ---


def test_extract_decision_reply_text_basic():
    from nonebot_plugin_hermes.core.hermes_client import maybe_extract_decision_reply_text

    out = maybe_extract_decision_reply_text('{"should_reply": true, "reply_text": "嗯嗯,知道了"}')
    assert out == "嗯嗯,知道了"


def test_extract_decision_reply_text_silent():
    from nonebot_plugin_hermes.core.hermes_client import maybe_extract_decision_reply_text

    # should_reply=false → 显式静默,返回空串(让调用方走静默分支)
    out = maybe_extract_decision_reply_text('{"should_reply": false, "topic_hint": "x"}')
    assert out == ""


def test_extract_decision_reply_text_not_decision():
    from nonebot_plugin_hermes.core.hermes_client import maybe_extract_decision_reply_text

    # 普通文字回复 → None,调用方继续用原文
    assert maybe_extract_decision_reply_text("今天天气真好") is None
    # 是 JSON 但不含 should_reply 字段 → 不算 submit_decision
    assert maybe_extract_decision_reply_text('{"foo": 1, "bar": 2}') is None


def test_extract_decision_reply_text_with_prefix():
    """LLM 输出常见 'sure! {...}' 形式;前缀文字不应阻止抽取。"""
    from nonebot_plugin_hermes.core.hermes_client import maybe_extract_decision_reply_text

    out = maybe_extract_decision_reply_text('noise before {"should_reply": true, "reply_text": "ok"}')
    assert out == "ok"


def test_extract_decision_reply_text_should_reply_no_text():
    """should_reply=true 但缺 reply_text → None(让调用方按未识别处理 / 走原文)。"""
    from nonebot_plugin_hermes.core.hermes_client import maybe_extract_decision_reply_text

    out = maybe_extract_decision_reply_text('{"should_reply": true}')
    assert out is None
