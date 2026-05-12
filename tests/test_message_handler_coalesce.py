"""消息 handler coalesce 行为集成测试。

直接调 _handle_reactive_path / _handle_passive_path,mock hermes_client.chat
让它 sleep 一段时间模拟慢上游,断言并发触发的 chat 调用次数被 coalesce。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

from nonebot_plugin_hermes import mcp as _mcp
from nonebot_plugin_hermes.core.active_session import ActiveSessionManager
from nonebot_plugin_hermes.core.bot_registry import BotRegistry
from nonebot_plugin_hermes.core.inflight import MAX_REFIRE_DEPTH, InflightRegistry
from nonebot_plugin_hermes.core.message_buffer import BufferedMessage, MessageBuffer


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

    # 用 wall-clock,因为 _refire 内部读 _now_ms() 做 is_active 校验
    now = int(time.time() * 1000)
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


@pytest.mark.asyncio
async def test_image_only_passive_in_window_skips_chat(monkeypatch):
    """active window 内、非显式触发、纯图无文本 → 不进 chat(),只写 buffer。"""
    from nonebot_plugin_hermes.handlers import message as handler_mod

    now = 3_000_000
    _mcp.active_sessions.trigger("ob11", "g1", "u1", now_ms=now)

    chat_mock = AsyncMock()
    monkeypatch.setattr(handler_mod.hermes_client, "chat", chat_mock)
    monkeypatch.setattr(handler_mod, "send_text_with_media", AsyncMock(return_value=True))

    target = _FakeTarget(id="g1", private=False)
    bot = _fake_bot()

    await handler_mod._handle_reactive_path(
        bot=bot,
        target=target,
        adapter_name="ob11",
        user_id="u2",
        group_id="g1",
        text="",
        image_urls=["http://example.com/cat.jpg"],
        is_explicit_trigger=False,
        now_ms=now + 100,
    )

    chat_mock.assert_not_called()


@pytest.mark.asyncio
async def test_image_with_text_passive_in_window_does_call_chat(monkeypatch):
    """active window 内、非显式触发、图 + 任意非空文本 → 进 chat()。"""
    from nonebot_plugin_hermes.handlers import message as handler_mod

    now = 3_100_000
    _mcp.active_sessions.trigger("ob11", "g1", "u1", now_ms=now)

    async def fake_chat(**kwargs):
        return _make_chat_result(text="ok")

    chat_mock = AsyncMock(side_effect=fake_chat)
    monkeypatch.setattr(handler_mod.hermes_client, "chat", chat_mock)
    monkeypatch.setattr(handler_mod, "send_text_with_media", AsyncMock(return_value=True))

    target = _FakeTarget(id="g1", private=False)
    bot = _fake_bot()

    await handler_mod._handle_reactive_path(
        bot=bot,
        target=target,
        adapter_name="ob11",
        user_id="u2",
        group_id="g1",
        text="看",
        image_urls=["http://example.com/cat.jpg"],
        is_explicit_trigger=False,
        now_ms=now + 100,
    )

    chat_mock.assert_called_once()


@pytest.mark.asyncio
async def test_image_only_explicit_trigger_does_call_chat(monkeypatch):
    """显式触发(@bot)+ 纯图 → 进 chat()(门控豁免)。"""
    from nonebot_plugin_hermes.handlers import message as handler_mod

    now = 3_200_000
    _mcp.active_sessions.trigger("ob11", "g1", "u1", now_ms=now)

    async def fake_chat(**kwargs):
        return _make_chat_result(text="ok")

    chat_mock = AsyncMock(side_effect=fake_chat)
    monkeypatch.setattr(handler_mod.hermes_client, "chat", chat_mock)
    monkeypatch.setattr(handler_mod, "send_text_with_media", AsyncMock(return_value=True))

    target = _FakeTarget(id="g1", private=False)
    bot = _fake_bot()

    await handler_mod._handle_reactive_path(
        bot=bot,
        target=target,
        adapter_name="ob11",
        user_id="u2",
        group_id="g1",
        text="",
        image_urls=["http://example.com/cat.jpg"],
        is_explicit_trigger=True,
        now_ms=now + 100,
    )

    chat_mock.assert_called_once()


@pytest.mark.asyncio
async def test_text_only_passive_in_window_does_call_chat(monkeypatch):
    """active window 内、非显式触发、纯文本无图 → 进 chat()(门控不适用)。"""
    from nonebot_plugin_hermes.handlers import message as handler_mod

    now = 3_300_000
    _mcp.active_sessions.trigger("ob11", "g1", "u1", now_ms=now)

    async def fake_chat(**kwargs):
        return _make_chat_result(text="ok")

    chat_mock = AsyncMock(side_effect=fake_chat)
    monkeypatch.setattr(handler_mod.hermes_client, "chat", chat_mock)
    monkeypatch.setattr(handler_mod, "send_text_with_media", AsyncMock(return_value=True))

    target = _FakeTarget(id="g1", private=False)
    bot = _fake_bot()

    await handler_mod._handle_reactive_path(
        bot=bot,
        target=target,
        adapter_name="ob11",
        user_id="u2",
        group_id="g1",
        text="hello",
        image_urls=[],
        is_explicit_trigger=False,
        now_ms=now + 100,
    )

    chat_mock.assert_called_once()


@pytest.mark.asyncio
async def test_refire_depth_caps_at_max(monkeypatch):
    """持续 burst:链尾最多重燃 MAX_REFIRE_DEPTH 次,触顶后 warn + drop pending。"""
    from nonebot_plugin_hermes.handlers import message as handler_mod

    # 用 wall-clock,因为 _refire 内部读 _now_ms() 做 is_active 校验
    now = int(time.time() * 1000)
    _mcp.active_sessions.trigger("ob11", "g1", "u1", now_ms=now)

    chat_calls: List[int] = []
    warning_messages: List[str] = []

    # Capture loguru warnings (nonebot uses loguru, not stdlib logging)
    original_warning = handler_mod.logger.warning

    def capture_warning(msg, *args, **kwargs):
        warning_messages.append(str(msg))
        return original_warning(msg, *args, **kwargs)

    monkeypatch.setattr(handler_mod.logger, "warning", capture_warning)

    async def chat_then_queue_more(**kwargs):
        chat_calls.append(len(chat_calls))
        # 每次 chat 跑期间,模拟有新消息塞 pending
        _mcp.inflight.try_enter(
            ("ob11", "group:g1"),
            BufferedMessage(
                ts=now + 1000 * (len(chat_calls) + 1),
                adapter="ob11",
                group_id="g1",
                user_id="u2",
                nickname="u2",
                content=f"queued-{len(chat_calls)}",
                image_urls=[],
                reply_to_ts=None,
                is_bot=False,
            ),
            now_ms=now + 1000 * (len(chat_calls) + 1),
        )
        return _make_chat_result(text=f"reply-{len(chat_calls)}")

    monkeypatch.setattr(handler_mod.hermes_client, "chat", chat_then_queue_more)
    monkeypatch.setattr(handler_mod, "send_text_with_media", AsyncMock(return_value=True))

    target = _FakeTarget(id="g1", private=False)
    bot = _fake_bot()

    await handler_mod._handle_reactive_path(
        bot=bot,
        target=target,
        adapter_name="ob11",
        user_id="u1",
        group_id="g1",
        text="trigger",
        image_urls=[],
        is_explicit_trigger=True,
        now_ms=now,
    )
    await asyncio.sleep(0.5)

    # 初发 1 + 重燃 3 = 4 次 chat,第 4 次重燃 depth=4 > MAX_REFIRE_DEPTH=3,被丢
    assert len(chat_calls) == 1 + MAX_REFIRE_DEPTH, f"got {len(chat_calls)}, expected {1 + MAX_REFIRE_DEPTH}"
    assert any("refire depth exceeded" in msg for msg in warning_messages), (
        f"Expected 'refire depth exceeded' warning, got: {warning_messages}"
    )


@pytest.mark.asyncio
async def test_transport_error_does_not_refire(monkeypatch):
    """上一发 is_transport_error=True 且 pending 已设 → 不重燃,pending 被丢。"""
    from nonebot_plugin_hermes.handlers import message as handler_mod

    now = 5_000_000
    _mcp.active_sessions.trigger("ob11", "g1", "u1", now_ms=now)

    chat_calls: List[int] = []

    async def transport_err_chat(**kwargs):
        chat_calls.append(len(chat_calls))
        if len(chat_calls) == 1:
            await asyncio.sleep(0.05)
            return _make_chat_result(text="err", transport_error=True)
        return _make_chat_result(text="ok")

    monkeypatch.setattr(handler_mod.hermes_client, "chat", transport_err_chat)
    monkeypatch.setattr(handler_mod, "send_text_with_media", AsyncMock(return_value=True))

    target = _FakeTarget(id="g1", private=False)
    bot = _fake_bot()

    main = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="u1",
            group_id="g1",
            text="trigger",
            image_urls=[],
            is_explicit_trigger=True,
            now_ms=now,
        )
    )
    await asyncio.sleep(0.01)
    pending_task = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="u1",
            group_id="g1",
            text="follow-up",
            image_urls=[],
            is_explicit_trigger=False,
            now_ms=now + 10,
        )
    )
    await asyncio.gather(main, pending_task)
    await asyncio.sleep(0.2)

    assert len(chat_calls) == 1, f"got {len(chat_calls)} chat calls; expected 1 (no refire on transport_error)"
    assert _mcp.inflight.take_pending(("ob11", "group:g1")) is None


@pytest.mark.asyncio
async def test_exception_in_turn_does_not_refire(monkeypatch):
    """_run_*_turn 抛 Exception → 不重燃,exception 仍冒泡。"""
    from nonebot_plugin_hermes.handlers import message as handler_mod

    now = 6_000_000
    _mcp.active_sessions.trigger("ob11", "g1", "u1", now_ms=now)

    chat_calls: List[int] = []

    async def boom_chat(**kwargs):
        chat_calls.append(len(chat_calls))
        await asyncio.sleep(0.05)
        raise RuntimeError("boom")

    monkeypatch.setattr(handler_mod.hermes_client, "chat", boom_chat)
    monkeypatch.setattr(handler_mod, "send_text_with_media", AsyncMock(return_value=True))

    target = _FakeTarget(id="g1", private=False)
    bot = _fake_bot()

    main = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="u1",
            group_id="g1",
            text="trigger",
            image_urls=[],
            is_explicit_trigger=True,
            now_ms=now,
        )
    )
    await asyncio.sleep(0.01)
    pending_task = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="u1",
            group_id="g1",
            text="follow",
            image_urls=[],
            is_explicit_trigger=False,
            now_ms=now + 10,
        )
    )
    with pytest.raises(RuntimeError, match="boom"):
        await main
    await pending_task
    await asyncio.sleep(0.1)

    assert len(chat_calls) == 1, "no refire on exception"
    assert _mcp.inflight.take_pending(("ob11", "group:g1")) is None


@pytest.mark.asyncio
async def test_refire_when_active_session_expired(monkeypatch):
    """重燃时 session 已过期 → _run_reactive_turn 返回 None,registry 干净 exit,不抛。"""
    from nonebot_plugin_hermes.handlers import message as handler_mod

    now = 7_000_000
    _mcp.active_sessions.trigger("ob11", "g1", "u1", now_ms=now)

    chat_calls: List[int] = []

    async def chat_and_expire(**kwargs):
        chat_calls.append(len(chat_calls))
        if len(chat_calls) == 1:
            await asyncio.sleep(0.05)
        # 第一发完成时:把 session 主动 end,让重燃看到 get_if_active=None
        _mcp.active_sessions.end("ob11", "g1")
        return _make_chat_result(text=f"reply-{len(chat_calls)}")

    monkeypatch.setattr(handler_mod.hermes_client, "chat", chat_and_expire)
    monkeypatch.setattr(handler_mod, "send_text_with_media", AsyncMock(return_value=True))

    target = _FakeTarget(id="g1", private=False)
    bot = _fake_bot()

    main = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="u1",
            group_id="g1",
            text="trigger",
            image_urls=[],
            is_explicit_trigger=True,
            now_ms=now,
        )
    )
    await asyncio.sleep(0.01)
    follow = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="u1",
            group_id="g1",
            text="follow",
            image_urls=[],
            is_explicit_trigger=False,
            now_ms=now + 10,
        )
    )
    await asyncio.gather(main, follow)
    await asyncio.sleep(0.2)

    # 主发 1 次 chat;重燃跑了但 _run_reactive_turn 立刻返回 None(session ended),
    # 不再次调 chat。
    assert len(chat_calls) == 1
    # registry 已 exit
    assert (
        _mcp.inflight.try_enter(
            ("ob11", "group:g1"),
            BufferedMessage(
                ts=now + 9999,
                adapter="ob11",
                group_id="g1",
                user_id="u1",
                nickname="u1",
                content="",
                image_urls=[],
                reply_to_ts=None,
                is_bot=False,
            ),
            now_ms=now + 9999,
        )
        == "entered"
    )
