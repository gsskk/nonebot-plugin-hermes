"""验证 `_ack_scope` async context manager 的所有分支。

不跑真实 chat() 流程——focus 在 context manager 的 set/clear/抑制语义。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _fake_event(message_id="abc123"):
    e = MagicMock()
    e.message_id = message_id
    return e


def _fake_bot():
    b = MagicMock()
    b.call_api = AsyncMock(return_value={})
    return b


@pytest.mark.asyncio
async def test_disabled_yields_without_api_call(monkeypatch):
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.handlers.message import _ack_scope

    monkeypatch.setattr(plugin_config, "hermes_ack_feedback_enabled", False)

    bot = _fake_bot()
    event = _fake_event()

    async with _ack_scope(bot, event, adapter_name="onebotv11", is_explicit_trigger=True):
        pass

    assert bot.call_api.await_count == 0


@pytest.mark.asyncio
async def test_non_explicit_trigger_yields_without_api_call(monkeypatch):
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.handlers.message import _ack_scope

    monkeypatch.setattr(plugin_config, "hermes_ack_feedback_enabled", True)

    bot = _fake_bot()
    event = _fake_event()

    async with _ack_scope(bot, event, adapter_name="onebotv11", is_explicit_trigger=False):
        pass

    assert bot.call_api.await_count == 0


@pytest.mark.asyncio
async def test_non_onebot_adapter_yields_without_api_call(monkeypatch):
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.handlers.message import _ack_scope

    monkeypatch.setattr(plugin_config, "hermes_ack_feedback_enabled", True)

    bot = _fake_bot()
    event = _fake_event()

    async with _ack_scope(bot, event, adapter_name="telegram", is_explicit_trigger=True):
        pass

    assert bot.call_api.await_count == 0


@pytest.mark.asyncio
async def test_missing_message_id_yields_without_api_call(monkeypatch):
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.handlers.message import _ack_scope

    monkeypatch.setattr(plugin_config, "hermes_ack_feedback_enabled", True)

    bot = _fake_bot()
    event = MagicMock(spec=[])  # 没有 message_id 属性

    async with _ack_scope(bot, event, adapter_name="onebotv11", is_explicit_trigger=True):
        pass

    assert bot.call_api.await_count == 0


@pytest.mark.asyncio
async def test_happy_path_sets_and_clears(monkeypatch):
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.handlers.message import _ack_scope

    monkeypatch.setattr(plugin_config, "hermes_ack_feedback_enabled", True)
    monkeypatch.setattr(plugin_config, "hermes_ack_emoji_id", "424")

    bot = _fake_bot()
    event = _fake_event(message_id=12345)

    async with _ack_scope(bot, event, adapter_name="onebotv11", is_explicit_trigger=True):
        pass

    assert bot.call_api.await_count == 2
    # 第一次 set=True 进, 第二次 set=False 出
    first_kwargs = bot.call_api.call_args_list[0].kwargs
    second_kwargs = bot.call_api.call_args_list[1].kwargs
    assert first_kwargs == {"message_id": 12345, "emoji_id": "424", "set": True}
    assert second_kwargs == {"message_id": 12345, "emoji_id": "424", "set": False}


@pytest.mark.asyncio
async def test_body_raises_still_clears(monkeypatch):
    """主路径抛异常时,finally 仍要 clear。"""
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.handlers.message import _ack_scope

    monkeypatch.setattr(plugin_config, "hermes_ack_feedback_enabled", True)

    bot = _fake_bot()
    event = _fake_event(message_id=12345)

    with pytest.raises(RuntimeError, match="boom"):
        async with _ack_scope(bot, event, adapter_name="onebotv11", is_explicit_trigger=True):
            raise RuntimeError("boom")

    # set 进 + clear 出, 异常被重抛
    assert bot.call_api.await_count == 2
    assert bot.call_api.call_args_list[1].kwargs["set"] is False


@pytest.mark.asyncio
async def test_set_fails_clear_skipped(monkeypatch):
    """set 失败 (网络/权限) 时, finally 不调 clear, 避免无意义错误日志。"""
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.handlers.message import _ack_scope

    monkeypatch.setattr(plugin_config, "hermes_ack_feedback_enabled", True)

    bot = MagicMock()
    bot.call_api = AsyncMock(side_effect=RuntimeError("api forbidden"))
    event = _fake_event(message_id=12345)

    async with _ack_scope(bot, event, adapter_name="onebotv11", is_explicit_trigger=True):
        pass

    # 只调了一次 (set), 没尝试 clear
    assert bot.call_api.await_count == 1


@pytest.mark.asyncio
async def test_clear_fails_silently(monkeypatch):
    """clear 失败时也 silently 吞掉, 不影响主路径。"""
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.handlers.message import _ack_scope

    monkeypatch.setattr(plugin_config, "hermes_ack_feedback_enabled", True)

    call_log = []

    async def flaky(*_args, **kw):
        call_log.append(kw)
        if kw.get("set") is False:
            raise RuntimeError("clear network err")
        return {}

    bot = MagicMock()
    bot.call_api = AsyncMock(side_effect=flaky)
    event = _fake_event(message_id=12345)

    # 不抛
    async with _ack_scope(bot, event, adapter_name="onebotv11", is_explicit_trigger=True):
        pass

    # 调过 set + clear 两次, clear 失败被吞
    assert len(call_log) == 2
