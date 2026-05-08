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
