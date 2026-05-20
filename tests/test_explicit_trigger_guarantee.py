"""Explicit-trigger 进 chat 不变量集成测试。

覆盖三类行为:
  - 排队的 explicit @ 在 _refire 路径上仍以 is_explicit_trigger=True 跑 chat
  - explicit pending 不被后到 bystander 覆盖
  - 失败路径(transport_error / depth-cap)按设计输出 user-visible signal
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
from nonebot_plugin_hermes.core.inflight import InflightRegistry
from nonebot_plugin_hermes.core.message_buffer import MessageBuffer
from nonebot_plugin_hermes.core.storage.image_cache import ImageCache
from nonebot_plugin_hermes.core.storage.image_fetcher import ImageFetcher
from nonebot_plugin_hermes.core.storage.message_store import MessageStore


@dataclass
class _FakeTarget:
    id: str
    private: bool = False
    adapter: str = "ob11"


def _fake_bot(self_id: str = "999"):
    bot = MagicMock()
    bot.self_id = self_id
    bot.call_api = AsyncMock()
    return bot


def _make_chat_result(text: str = "ok", transport_error: bool = False, structured=None):
    from nonebot_plugin_hermes.core.hermes_client import ChatResult

    if structured is None and not transport_error:
        structured = {"should_reply": True, "reply_text": text, "should_exit_active": False}
    return ChatResult(
        raw_text=text,
        media_urls=[],
        structured=structured,
        parse_failed=False,
        is_transport_error=transport_error,
    )


@pytest.fixture(autouse=True)
def _setup_runtime(monkeypatch, tmp_path):
    store = MessageStore(db_path=tmp_path / "messages.db")
    cache = ImageCache(cache_dir=tmp_path / "imgs", quota_bytes=1024 * 1024)
    fetcher = ImageFetcher(store=store, cache=cache)
    _mcp.message_buffer = MessageBuffer(store=store, fetcher=fetcher)
    _mcp.active_sessions = ActiveSessionManager(default_ttl_sec=300)
    _mcp.bot_registry = BotRegistry()
    _mcp.inflight = InflightRegistry()
    yield
    _mcp.message_buffer = None
    _mcp.active_sessions = None
    _mcp.bot_registry = None
    _mcp.inflight = None
    store.close()


@pytest.mark.asyncio
async def test_inflight_explicit_at_replies_via_refire(monkeypatch):
    """in-flight 期间到达的 explicit @ → refire 时仍以 is_explicit_trigger=True 调 chat。"""
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.handlers import message as handler_mod

    monkeypatch.setattr(plugin_config, "hermes_reactive_post_reply_cooldown_sec", 0)

    now = int(time.time() * 1000)
    _mcp.active_sessions.trigger("ob11", "g1", "u1", now_ms=now)

    chat_args: List[dict] = []

    async def slow_chat(**kwargs):
        chat_args.append(kwargs)
        await asyncio.sleep(0.1)
        # decision-shaped result,在 reactive 路径下 _run_reactive_turn 才会发 reply
        return _make_chat_result(text=f"reply-{len(chat_args)}")

    monkeypatch.setattr(handler_mod.hermes_client, "chat", slow_chat)
    monkeypatch.setattr(handler_mod, "send_text_with_media", AsyncMock(return_value=True))

    target = _FakeTarget(id="g1", private=False)
    bot = _fake_bot()

    # 第一发 user-A explicit @bot
    t1 = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="user-A",
            group_id="g1",
            text="hello",
            image_urls=[],
            is_explicit_trigger=True,
            now_ms=now,
        )
    )
    # 第二发 user-B explicit @bot 紧随其后,会落进 pending
    await asyncio.sleep(0.01)
    t2 = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="user-B",
            group_id="g1",
            text="me too",
            image_urls=[],
            is_explicit_trigger=True,
            now_ms=now + 1,
        )
    )
    await asyncio.gather(t1, t2)
    await asyncio.sleep(0.3)

    # 应该至少调 2 次 chat(初发 user-A + refire user-B)
    assert len(chat_args) >= 2, f"chat 只被调用 {len(chat_args)} 次"
    # 第二次(refire)必须是 reactive mode
    assert chat_args[1].get("mode") == "reactive"
    # _run_reactive_turn 会把 user_id 传给 chat,我们只断言第二次是 user-B
    assert chat_args[1].get("user_id") == "user-B"


@pytest.mark.asyncio
async def test_refire_cooldown_bypass_for_explicit_pending(monkeypatch):
    """post-reply cooldown 窗内排队的 explicit @ → refire 跑 chat,不被 cooldown 吞掉。"""
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.handlers import message as handler_mod

    # cooldown 开,默认 8s
    monkeypatch.setattr(plugin_config, "hermes_reactive_post_reply_cooldown_sec", 8)

    now = int(time.time() * 1000)
    _mcp.active_sessions.trigger("ob11", "g1", "u1", now_ms=now)

    chat_args: List[dict] = []

    async def slow_chat(**kwargs):
        chat_args.append(kwargs)
        await asyncio.sleep(0.1)
        return _make_chat_result(text=f"reply-{len(chat_args)}")

    monkeypatch.setattr(handler_mod.hermes_client, "chat", slow_chat)
    monkeypatch.setattr(handler_mod, "send_text_with_media", AsyncMock(return_value=True))

    target = _FakeTarget(id="g1", private=False)
    bot = _fake_bot()

    # 第一发会触发 mark_bot_replied,把 cooldown 闸门起来
    t1 = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="user-A",
            group_id="g1",
            text="hello",
            image_urls=[],
            is_explicit_trigger=True,
            now_ms=now,
            event_msg_id=1001,
        )
    )
    # 第二发 explicit @bot 在第一发还没回完时进 pending
    await asyncio.sleep(0.01)
    t2 = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="user-B",
            group_id="g1",
            text="me too",
            image_urls=[],
            is_explicit_trigger=True,
            now_ms=now + 1,
            event_msg_id=1002,
        )
    )
    await asyncio.gather(t1, t2)
    await asyncio.sleep(0.3)

    # cooldown 不应该阻止 explicit refire:两发 chat 都要发生
    assert len(chat_args) == 2, f"explicit refire 被 cooldown 吞掉,chat 只调用了 {len(chat_args)} 次"


@pytest.mark.asyncio
async def test_refire_cooldown_still_blocks_bystander_pending(monkeypatch):
    """post-reply cooldown 窗内排队的 bystander → refire 被 cooldown 吞掉(原行为不变)。"""
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.handlers import message as handler_mod

    monkeypatch.setattr(plugin_config, "hermes_reactive_post_reply_cooldown_sec", 8)

    now = int(time.time() * 1000)
    _mcp.active_sessions.trigger("ob11", "g1", "u1", now_ms=now)

    chat_args: List[dict] = []

    async def slow_chat(**kwargs):
        chat_args.append(kwargs)
        await asyncio.sleep(0.1)
        return _make_chat_result(text=f"reply-{len(chat_args)}")

    monkeypatch.setattr(handler_mod.hermes_client, "chat", slow_chat)
    monkeypatch.setattr(handler_mod, "send_text_with_media", AsyncMock(return_value=True))

    target = _FakeTarget(id="g1", private=False)
    bot = _fake_bot()

    t1 = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="user-A",
            group_id="g1",
            text="hello",
            image_urls=[],
            is_explicit_trigger=True,
            now_ms=now,
        )
    )
    await asyncio.sleep(0.01)
    # 第二发是 bystander(非 explicit)
    t2 = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="user-B",
            group_id="g1",
            text="someone says something",
            image_urls=[],
            is_explicit_trigger=False,
            now_ms=now + 1,
        )
    )
    await asyncio.gather(t1, t2)
    await asyncio.sleep(0.3)

    # bystander refire 应该被 cooldown 吞掉,只有第一发 chat
    assert len(chat_args) == 1, f"bystander 不应被 refire 跑,但 chat 调用了 {len(chat_args)} 次"


@pytest.mark.asyncio
async def test_emit_busy_notice_onebotv11_calls_set_emoji():
    """onebotv11 + msg_id 存在 → 调 set_msg_emoji_like with hermes_busy_emoji_id。"""
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.handlers import message as handler_mod

    bot = _fake_bot()
    await handler_mod._emit_busy_notice(bot, "onebotv11", 12345)

    bot.call_api.assert_awaited_once_with(
        "set_msg_emoji_like",
        message_id=12345,
        emoji_id=plugin_config.hermes_busy_emoji_id,
    )


@pytest.mark.asyncio
async def test_emit_busy_notice_no_op_for_non_onebotv11(monkeypatch):
    """adapter 非 onebotv11 → 不调 API,WARN 日志。"""
    from nonebot_plugin_hermes.handlers import message as handler_mod

    warn_messages: list[str] = []
    monkeypatch.setattr(handler_mod.logger, "warning", lambda msg, *a, **kw: warn_messages.append(str(msg)))

    bot = _fake_bot()
    await handler_mod._emit_busy_notice(bot, "telegram", 12345)

    bot.call_api.assert_not_awaited()
    assert any("busy_notice" in m and "no-op" in m for m in warn_messages)


@pytest.mark.asyncio
async def test_emit_busy_notice_no_op_when_msg_id_none(monkeypatch):
    """msg_id 缺失 → 不调 API,WARN 日志。"""
    from nonebot_plugin_hermes.handlers import message as handler_mod

    warn_messages: list[str] = []
    monkeypatch.setattr(handler_mod.logger, "warning", lambda msg, *a, **kw: warn_messages.append(str(msg)))

    bot = _fake_bot()
    await handler_mod._emit_busy_notice(bot, "onebotv11", None)

    bot.call_api.assert_not_awaited()
    assert any("busy_notice" in m and "no-op" in m for m in warn_messages)


@pytest.mark.asyncio
async def test_emit_busy_notice_swallows_api_error(monkeypatch):
    """API 抛错 → swallow + DEBUG 日志,不冒泡。"""
    from nonebot_plugin_hermes.handlers import message as handler_mod

    debug_messages: list[str] = []
    monkeypatch.setattr(handler_mod.logger, "debug", lambda msg, *a, **kw: debug_messages.append(str(msg)))

    bot = _fake_bot()
    bot.call_api.side_effect = RuntimeError("emoji api down")

    # 不抛异常即测试成功
    await handler_mod._emit_busy_notice(bot, "onebotv11", 12345)

    assert any("busy_notice" in m and "emit failed" in m for m in debug_messages)


@pytest.mark.asyncio
async def test_refire_depth_cap_explicit_emits_busy_emoji(monkeypatch):
    """refire 链触顶 + pending 是 explicit + msg_id 有 → 调 set_msg_emoji_like with busy emoji_id。"""
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.core.inflight import MAX_REFIRE_DEPTH
    from nonebot_plugin_hermes.core.message_buffer import BufferedMessage
    from nonebot_plugin_hermes.handlers import message as handler_mod

    bot = _fake_bot()
    target = _FakeTarget(id="g1", private=False)

    # 直接调 _refire 触发 depth-cap 分支,跳过 burst orchestration
    trigger_msg = BufferedMessage(
        ts=int(time.time() * 1000),
        adapter="onebotv11",
        group_id="g1",
        user_id="user-B",
        nickname="B",
        content="me too",
        image_urls=[],
        reply_to_ts=None,
        is_bot=False,
    )
    # 占住 inflight slot 以便 _refire 内部 exit 不报错
    _mcp.inflight.try_enter(
        ("onebotv11", "group:g1"),
        trigger_msg,
        is_explicit_trigger=True,
        original_msg_id=9999,
        now_ms=trigger_msg.ts,
    )

    await handler_mod._refire(
        key=("onebotv11", "group:g1"),
        trigger_msg=trigger_msg,
        is_explicit_trigger=True,
        original_msg_id=9999,
        depth=MAX_REFIRE_DEPTH + 1,
        mode="reactive",
        bot=bot,
        target=target,
        adapter_name="onebotv11",
        group_id="g1",
    )

    bot.call_api.assert_awaited_once_with(
        "set_msg_emoji_like",
        message_id=9999,
        emoji_id=plugin_config.hermes_busy_emoji_id,
    )


@pytest.mark.asyncio
async def test_refire_depth_cap_bystander_no_emoji():
    """refire 链触顶 + pending 是 bystander → 只 WARN 日志,不调 emoji API。"""
    from nonebot_plugin_hermes.core.inflight import MAX_REFIRE_DEPTH
    from nonebot_plugin_hermes.core.message_buffer import BufferedMessage
    from nonebot_plugin_hermes.handlers import message as handler_mod

    bot = _fake_bot()
    target = _FakeTarget(id="g1", private=False)
    trigger_msg = BufferedMessage(
        ts=int(time.time() * 1000),
        adapter="ob11",
        group_id="g1",
        user_id="user-B",
        nickname="B",
        content="something",
        image_urls=[],
        reply_to_ts=None,
        is_bot=False,
    )
    _mcp.inflight.try_enter(
        ("ob11", "group:g1"),
        trigger_msg,
        is_explicit_trigger=False,
        original_msg_id=None,
        now_ms=trigger_msg.ts,
    )

    await handler_mod._refire(
        key=("ob11", "group:g1"),
        trigger_msg=trigger_msg,
        is_explicit_trigger=False,
        original_msg_id=None,
        depth=MAX_REFIRE_DEPTH + 1,
        mode="reactive",
        bot=bot,
        target=target,
        adapter_name="ob11",
        group_id="g1",
    )

    bot.call_api.assert_not_awaited()


@pytest.mark.asyncio
async def test_refire_depth_cap_explicit_no_msg_id_warn_only(monkeypatch):
    """refire 链触顶 + pending 是 explicit 但 msg_id=None → 不调 emoji API,WARN 日志。"""
    from nonebot_plugin_hermes.core.inflight import MAX_REFIRE_DEPTH
    from nonebot_plugin_hermes.core.message_buffer import BufferedMessage
    from nonebot_plugin_hermes.handlers import message as handler_mod

    warn_messages: list[str] = []
    monkeypatch.setattr(handler_mod.logger, "warning", lambda msg, *a, **kw: warn_messages.append(str(msg)))

    bot = _fake_bot()
    target = _FakeTarget(id="g1", private=False)
    trigger_msg = BufferedMessage(
        ts=int(time.time() * 1000),
        adapter="ob11",
        group_id="g1",
        user_id="user-B",
        nickname="B",
        content="x",
        image_urls=[],
        reply_to_ts=None,
        is_bot=False,
    )
    _mcp.inflight.try_enter(
        ("ob11", "group:g1"),
        trigger_msg,
        is_explicit_trigger=True,
        original_msg_id=None,
        now_ms=trigger_msg.ts,
    )

    await handler_mod._refire(
        key=("ob11", "group:g1"),
        trigger_msg=trigger_msg,
        is_explicit_trigger=True,
        original_msg_id=None,
        depth=MAX_REFIRE_DEPTH + 1,
        mode="reactive",
        bot=bot,
        target=target,
        adapter_name="ob11",
        group_id="g1",
    )

    bot.call_api.assert_not_awaited()
    assert any("busy_notice" in m and "no-op" in m for m in warn_messages)


@pytest.mark.asyncio
async def test_refire_transport_error_explicit_sends_fallback(monkeypatch):
    """refire 路径 chat 返 transport_error + pending 是 explicit → 发 fallback_text。"""
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.handlers import message as handler_mod

    monkeypatch.setattr(plugin_config, "hermes_reactive_post_reply_cooldown_sec", 0)
    monkeypatch.setattr(plugin_config, "hermes_transport_error_fallback_text", "我这边遇到点状况,稍后再问一次")

    now = int(time.time() * 1000)
    _mcp.active_sessions.trigger("ob11", "g1", "user-A", now_ms=now)

    chat_call = {"count": 0}

    async def chat_first_ok_then_transport_err(**kwargs):
        chat_call["count"] += 1
        await asyncio.sleep(0.05)
        if chat_call["count"] == 1:
            return _make_chat_result(text="first ok")
        return _make_chat_result(text="ignored upstream error noise", transport_error=True)

    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(handler_mod.hermes_client, "chat", chat_first_ok_then_transport_err)
    monkeypatch.setattr(handler_mod, "send_text_with_media", send_mock)

    target = _FakeTarget(id="g1", private=False)
    bot = _fake_bot()

    t1 = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="user-A",
            group_id="g1",
            text="hello",
            image_urls=[],
            is_explicit_trigger=True,
            now_ms=now,
            event_msg_id=1001,
        )
    )
    await asyncio.sleep(0.01)
    t2 = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="user-B",
            group_id="g1",
            text="me too",
            image_urls=[],
            is_explicit_trigger=True,
            now_ms=now + 1,
            event_msg_id=1002,
        )
    )
    await asyncio.gather(t1, t2)
    await asyncio.sleep(0.3)

    # send 应该被调 2 次:第一发正常回 "first ok",第二发 fallback_text
    assert send_mock.await_count == 2
    last_call = send_mock.await_args_list[-1]
    assert last_call.kwargs.get("text") == "我这边遇到点状况,稍后再问一次"


@pytest.mark.asyncio
async def test_refire_transport_error_bystander_no_fallback(monkeypatch):
    """refire 路径 chat 返 transport_error + pending 是 bystander → 不发 fallback(原行为)。"""
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.handlers import message as handler_mod

    monkeypatch.setattr(plugin_config, "hermes_reactive_post_reply_cooldown_sec", 0)
    monkeypatch.setattr(plugin_config, "hermes_transport_error_fallback_text", "fallback text")

    now = int(time.time() * 1000)
    _mcp.active_sessions.trigger("ob11", "g1", "user-A", now_ms=now)

    chat_call = {"count": 0}

    async def chat_first_ok_then_transport_err(**kwargs):
        chat_call["count"] += 1
        await asyncio.sleep(0.05)
        if chat_call["count"] == 1:
            return _make_chat_result(text="first ok")
        return _make_chat_result(text="x", transport_error=True)

    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(handler_mod.hermes_client, "chat", chat_first_ok_then_transport_err)
    monkeypatch.setattr(handler_mod, "send_text_with_media", send_mock)

    target = _FakeTarget(id="g1", private=False)
    bot = _fake_bot()

    t1 = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="user-A",
            group_id="g1",
            text="hello",
            image_urls=[],
            is_explicit_trigger=True,
            now_ms=now,
        )
    )
    await asyncio.sleep(0.01)
    t2 = asyncio.create_task(
        handler_mod._handle_reactive_path(
            bot=bot,
            target=target,
            adapter_name="ob11",
            user_id="user-B",
            group_id="g1",
            text="bystander chatter",
            image_urls=[],
            is_explicit_trigger=False,
            now_ms=now + 1,
        )
    )
    await asyncio.gather(t1, t2)
    await asyncio.sleep(0.3)

    # send 应该只被调 1 次:第一发回 "first ok",bystander 失败静默
    assert send_mock.await_count == 1
