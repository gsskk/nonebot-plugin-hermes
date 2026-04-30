"""
命令处理器

/clear, /help, /ping 等内置命令。
"""

from __future__ import annotations

import nonebot_plugin_alconna as alconna
from nonebot import on_command
from nonebot.adapters import Bot, Event

from ..core.hermes_client import hermes_client
from ..core.session import session_manager


def _get_adapter_name(target: alconna.Target) -> str:
    adapter = getattr(target, "adapter", "") or ""
    return adapter.lower().replace(" ", "").replace(".", "") or "unknown"


# --- /clear ---
clear_command = on_command("clear", force_whitespace=True, priority=90, block=True)


@clear_command.handle()
async def handle_clear(bot: Bot, event: Event):
    """重置当前会话"""
    target = alconna.get_target()
    adapter_name = _get_adapter_name(target)
    user_id = event.get_user_id() or "user"
    group_id = None if target.private else target.id

    session_manager.clear_session(
        adapter_name=adapter_name,
        is_private=target.private,
        user_id=user_id,
        group_id=group_id,
    )

    reply = alconna.UniMessage("✅ 会话已重置，开始新的对话。")
    if not target.private:
        reply = alconna.UniMessage([alconna.At("user", user_id), "\n"]) + reply

    await reply.send(target=target, bot=bot)


# --- /ping ---
ping_command = on_command("ping", force_whitespace=True, priority=90, block=True)


@ping_command.handle()
async def handle_ping(bot: Bot, event: Event):
    """检查 Hermes 连接状态"""
    target = alconna.get_target()

    healthy = await hermes_client.health_check()
    if healthy:
        msg = "🏓 pong! Hermes Agent 连接正常。"
    else:
        msg = "⚠️ 无法连接到 Hermes Agent，请检查 Gateway 是否正在运行。"

    await alconna.UniMessage(msg).send(target=target, bot=bot)


# --- /help ---
help_command = on_command("help", aliases={"帮助"}, force_whitespace=True, priority=90, block=True)


@help_command.handle()
async def handle_help(bot: Bot, event: Event):
    """显示帮助信息"""
    target = alconna.get_target()

    if target.private:
        help_text = (
            "🤖 Hermes Agent 帮助\n\n"
            "直接发送消息即可与 AI 对话。\n\n"
            "命令：\n"
            "/clear - 重置对话\n"
            "/ping - 检查连接状态\n"
            "/help - 显示本帮助"
        )
    else:
        help_text = (
            "🤖 Hermes Agent 帮助\n\n"
            "@我 发送消息即可与 AI 对话。\n\n"
            "命令：\n"
            "/clear - 重置对话\n"
            "/ping - 检查连接状态\n"
            "/help - 显示本帮助"
        )

    await alconna.UniMessage(help_text).send(target=target, bot=bot)
