"""消息 handler coalesce 行为集成测试。

直接调 _handle_reactive_path / _handle_passive_path,mock hermes_client.chat
让它 sleep 一段时间模拟慢上游,断言并发触发的 chat 调用次数被 coalesce。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

from nonebot_plugin_hermes import mcp as _mcp
from nonebot_plugin_hermes.core.active_session import ActiveSessionManager
from nonebot_plugin_hermes.core.bot_registry import BotRegistry
from nonebot_plugin_hermes.core.inflight import InflightRegistry
from nonebot_plugin_hermes.core.message_buffer import MessageBuffer


@dataclass
class _FakeTarget:
    id: str
    private: bool = False
    adapter: str = "ob11"


def _fake_bot(self_id: str = "999"):
    bot = MagicMock()
    bot.self_id = self_id
    return bot


@pytest.fixture(autouse=True)
def _setup_runtime(monkeypatch):
    """每个测试用例独立运行时单例。"""
    _mcp.message_buffer = MessageBuffer(per_group_cap=50, total_groups_cap=10)
    _mcp.active_sessions = ActiveSessionManager(default_ttl_sec=300)
    _mcp.bot_registry = BotRegistry()
    _mcp.inflight = InflightRegistry()
    yield
    _mcp.message_buffer = None
    _mcp.active_sessions = None
    _mcp.bot_registry = None
    _mcp.inflight = None


def _make_chat_result(text: str = "ok", transport_error: bool = False, structured=None):
    """造一个 ChatResult-like。reactive 需要 structured;passive 用 raw_text。"""
    from nonebot_plugin_hermes.core.hermes_client import ChatResult

    return ChatResult(
        raw_text=text,
        media_urls=[],
        structured=structured or {"should_reply": True, "reply_text": text, "should_exit_active": False},
        parse_failed=False,
        is_transport_error=transport_error,
    )


@pytest.mark.asyncio
async def test_reactive_burst_coalesces_to_two_chat_calls(monkeypatch):
    """同一 group 上 5 条 burst,chat 实际被调 2 次(初发 + 一次合并重燃)。"""
    from nonebot_plugin_hermes.handlers import message as handler_mod

    now = 1_000_000
    _mcp.active_sessions.trigger("ob11", "g1", "u1", now_ms=now)

    chat_calls: List[int] = []

    async def slow_chat(**kwargs):
        chat_calls.append(len(chat_calls))
        await asyncio.sleep(0.1)
        return _make_chat_result(text=f"reply-{len(chat_calls)}")

    monkeypatch.setattr(handler_mod.hermes_client, "chat", slow_chat)
    monkeypatch.setattr(handler_mod, "send_text_with_media", AsyncMock(return_value=True))

    target = _FakeTarget(id="g1", private=False)
    bot = _fake_bot()

    tasks = []
    for i in range(5):
        tasks.append(
            asyncio.create_task(
                handler_mod._handle_reactive_path(
                    bot=bot,
                    target=target,
                    adapter_name="ob11",
                    user_id="u1",
                    group_id="g1",
                    text=f"msg-{i}",
                    image_urls=[],
                    is_explicit_trigger=False,
                    now_ms=now + i,
                )
            )
        )
    await asyncio.gather(*tasks)
    await asyncio.sleep(0.3)

    assert len(chat_calls) == 2, f"got {len(chat_calls)} chat calls, expected 2"


@pytest.mark.asyncio
async def test_passive_private_burst_coalesces(monkeypatch):
    """私聊连发 3 条,chat 实际被调 2 次(初发 + 合并重燃)。"""
    from nonebot_plugin_hermes.handlers import message as handler_mod
    from nonebot_plugin_hermes.core.hermes_client import ChatResult

    chat_calls: List[int] = []

    async def slow_chat_passive(**kwargs):
        chat_calls.append(len(chat_calls))
        await asyncio.sleep(0.1)
        return ChatResult(
            raw_text=f"reply-{len(chat_calls)}",
            media_urls=[],
            structured=None,
            parse_failed=False,
            is_transport_error=False,
        )

    monkeypatch.setattr(handler_mod.hermes_client, "chat", slow_chat_passive)
    monkeypatch.setattr(handler_mod, "send_text_with_media", AsyncMock(return_value=True))

    target = _FakeTarget(id="u1", private=True)
    bot = _fake_bot()
    now = 2_000_000

    tasks = []
    for i in range(3):
        tasks.append(
            asyncio.create_task(
                handler_mod._handle_passive_path(
                    bot=bot,
                    target=target,
                    adapter_name="ob11",
                    user_id="u1",
                    group_id=None,
                    text=f"msg-{i}",
                    image_urls=[],
                    is_private=True,
                    now_ms=now + i,
                )
            )
        )
    await asyncio.gather(*tasks)
    await asyncio.sleep(0.3)

    assert len(chat_calls) == 2, f"got {len(chat_calls)} chat calls, expected 2"
