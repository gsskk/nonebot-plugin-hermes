"""Session 持久化失败拦截、即时重试与静默处理测试"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest import MonkeyPatch

from nonebot_plugin_hermes.core.hermes_client import (
    ChatResult,
    HermesClient,
    is_persistence_error_text,
)
from nonebot_plugin_hermes.core.session import session_manager
from nonebot_plugin_hermes.handlers.message import _run_passive_turn


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


def test_is_persistence_error_text():
    err1 = (
        "No reply: the turn was stopped because session storage could not be written "
        "(the transcript would have been lost on restart). Check the state database health (`hermes doctor`), then send your message again."
    )
    err2 = (
        "No reply: the turn was stopped because session storage was busy "
        "(another Hermes process was writing to the state database)."
    )
    normal = "你好，我是 Hermes AI 助手。"

    assert is_persistence_error_text(err1) is True
    assert is_persistence_error_text(err2) is True
    assert is_persistence_error_text(normal) is False
    assert is_persistence_error_text("") is False


@pytest.mark.asyncio
async def test_hermes_client_flags_persistence_error(monkeypatch: MonkeyPatch):
    err_text = (
        "No reply: the turn was stopped because session storage could not be written "
        "(the transcript would have been lost on restart)."
    )
    body = {"choices": [{"message": {"content": err_text}}]}

    def factory(*args: Any, **kwargs: Any) -> _MockClient:
        return _MockClient(response=_MockResponse(200, body))

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    client = HermesClient()
    res = await client.chat(
        text="test",
        session_key="s1",
        user_id="u1",
        group_id="g1",
        adapter_name="ob11",
        is_private=False,
    )

    assert res.is_persistence_error is True
    assert res.is_transport_error is True
    assert res.parse_failed is True
    assert res.raw_text == err_text


@pytest.mark.asyncio
async def test_run_passive_turn_retries_on_persistence_error(monkeypatch: MonkeyPatch):
    """测试 Passive 模式下，第一次遇到 Persistence Error 时自动重置 Session 并即时重试成功"""
    bot = MagicMock()
    target = MagicMock()
    target.id = "g1"
    target.private = False

    session_manager.clear_session("ob11", False, "u1", "g1")
    init_key = session_manager.get_session_key("ob11", False, "u1", "g1")

    err_result = ChatResult(
        raw_text="the turn was stopped because session storage could not be written",
        parse_failed=True,
        is_transport_error=True,
        is_persistence_error=True,
    )
    success_result = ChatResult(
        raw_text="这是重试成功后的模型回复",
        media_urls=[],
    )

    chat_mock = AsyncMock(side_effect=[err_result, success_result])
    monkeypatch.setattr("nonebot_plugin_hermes.handlers.message.hermes_client.chat", chat_mock)

    send_mock = AsyncMock()
    monkeypatch.setattr("nonebot_plugin_hermes.handlers.message.send_text_with_media", send_mock)

    res = await _run_passive_turn(
        bot=bot,
        target=target,
        adapter_name="ob11",
        user_id="u1",
        group_id="g1",
        is_private=False,
        text="hello",
        image_urls=[],
        now_ms=1000,
    )

    assert chat_mock.call_count == 2
    # 第二次调用时使用了新的 session_key
    retry_session_key = chat_mock.call_args_list[1].kwargs["session_key"]
    assert retry_session_key != init_key

    # 验证最终发给用户的是重试成功后的回复，而不是报错文本
    send_mock.assert_called_once()
    assert send_mock.call_args.kwargs["text"] == "这是重试成功后的模型回复"
    assert res == success_result


@pytest.mark.asyncio
async def test_run_passive_turn_silences_persistent_error(monkeypatch: MonkeyPatch):
    """测试当即时重试依然失败时，原始报错文本被静默屏蔽（配空 fallback_text 时完全静默）"""
    bot = MagicMock()
    target = MagicMock()
    target.id = "g1"
    target.private = False

    monkeypatch.setattr("nonebot_plugin_hermes.handlers.message.plugin_config.hermes_transport_error_fallback_text", "")

    err_result = ChatResult(
        raw_text="the turn was stopped because session storage could not be written",
        parse_failed=True,
        is_transport_error=True,
        is_persistence_error=True,
    )

    chat_mock = AsyncMock(side_effect=[err_result, err_result])
    monkeypatch.setattr("nonebot_plugin_hermes.handlers.message.hermes_client.chat", chat_mock)

    send_mock = AsyncMock()
    monkeypatch.setattr("nonebot_plugin_hermes.handlers.message.send_text_with_media", send_mock)

    res = await _run_passive_turn(
        bot=bot,
        target=target,
        adapter_name="ob11",
        user_id="u1",
        group_id="g1",
        is_private=False,
        text="hello",
        image_urls=[],
        now_ms=1000,
    )

    assert chat_mock.call_count == 2
    # 验证两次重试都失败后，由于 is_transport_error=True 且 fallback 为空，send_text_with_media 未被调用（静默）
    send_mock.assert_not_called()
    assert res == err_result
