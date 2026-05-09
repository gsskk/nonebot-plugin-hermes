"""
命令处理器

/clear, /help, /ping, /hermes-status 等内置命令。
"""

from __future__ import annotations

import time

import nonebot_plugin_alconna as alconna
from nonebot import logger, on_command
from nonebot.adapters import Bot, Event
from nonebot.matcher import Matcher

from .. import mcp as _mcp
from ..config import plugin_config
from ..core.hermes_client import hermes_client
from ..core.session import session_manager
from ..utils import check_isolation, get_adapter_name


# --- /clear ---
clear_command = on_command("clear", force_whitespace=True, priority=88, block=True)


@clear_command.handle()
async def handle_clear(bot: Bot, event: Event, matcher: Matcher):
    """重置当前会话"""
    target = alconna.get_target()
    if not check_isolation(event, target):
        matcher.skip()

    adapter_name = get_adapter_name(target)
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
ping_command = on_command("ping", force_whitespace=True, priority=88, block=True)


@ping_command.handle()
async def handle_ping(bot: Bot, event: Event, matcher: Matcher):
    """检查 Hermes 连接状态"""
    target = alconna.get_target()
    if not check_isolation(event, target):
        matcher.skip()

    healthy = await hermes_client.health_check()
    if healthy:
        msg = "🏓 pong! Hermes Agent 连接正常。"
    else:
        msg = "⚠️ 无法连接到 Hermes Agent，请检查 Gateway 是否正在运行。"

    await alconna.UniMessage(msg).send(target=target, bot=bot)


# --- /help ---
help_command = on_command("help", aliases={"帮助"}, force_whitespace=True, priority=88, block=True)


@help_command.handle()
async def handle_help(bot: Bot, event: Event, matcher: Matcher):
    """显示帮助信息"""
    target = alconna.get_target()
    if not check_isolation(event, target):
        matcher.skip()

    # 是否管理员决定要不要把 /hermes-status 暴露给当前用户
    adapter_name = get_adapter_name(target)
    user_id = event.get_user_id() or ""
    is_admin = f"{adapter_name}:{user_id}" in plugin_config.hermes_admin_users

    if target.private:
        intro = "🤖 Hermes Agent 帮助\n\n直接发送消息即可与 AI 对话。\n\n命令：\n"
    else:
        intro = "🤖 Hermes Agent 帮助\n\n@我 发送消息即可与 AI 对话。\n\n命令：\n"

    lines = [
        "/clear - 重置对话",
        "/ping - 检查连接状态",
        "/help - 显示本帮助",
    ]
    if is_admin:
        # 管理员才看见运行时状态命令,普通用户视角下此命令"不存在"
        lines.append("/hermes-status - 查看插件运行时状态(管理员)")

    help_text = intro + "\n".join(lines)
    await alconna.UniMessage(help_text).send(target=target, bot=bot)


# --- /hermes-status ---
status_command = on_command("hermes-status", force_whitespace=True, priority=88, block=True)


@status_command.handle()
async def handle_status(bot: Bot, event: Event, matcher: Matcher):
    """打印插件 M1-mem 运行时状态:MCP / 活跃 session / buffer / registry。"""
    target = alconna.get_target()
    if not check_isolation(event, target):
        matcher.skip()

    # /hermes-status 暴露内部运行时(活跃群、buffer 内容、bot 路由),
    # 应限制在管理员白名单内。**隐身策略**:对非管理员完全静默,不发"未授权"
    # 提示——避免把命令存在性暴露给一般用户。空集 = deny by default。
    adapter_name = get_adapter_name(target)
    user_id = event.get_user_id() or ""
    admin_key = f"{adapter_name}:{user_id}"
    if admin_key not in plugin_config.hermes_admin_users:
        logger.debug(f"[HERMES] /hermes-status silent skip for {admin_key}")
        return  # block=True 已阻断后续 matcher,直接 return 即静默

    now_ms = int(time.time() * 1000)

    # MCP 状态
    mcp_line = (
        f"on @ {plugin_config.hermes_mcp_host}:{plugin_config.hermes_mcp_port}"
        if plugin_config.hermes_mcp_enabled
        else "off"
    )
    active_line = "on" if plugin_config.hermes_active_session_enabled else "off"

    # ActiveSessionManager:统计当前未过期 session
    active_count = 0
    active_details: list[str] = []
    if _mcp.active_sessions is not None:
        for s in _mcp.active_sessions.list():
            ttl_left = max(0, (s.expires_at - now_ms) // 1000)
            if ttl_left > 0:
                active_count += 1
                topic = f" topic={s.topic_hint}" if s.topic_hint else ""
                active_details.append(f"  - {s.adapter}/{s.group_id} by {s.triggered_by} ttl={ttl_left}s{topic}")

    # MessageBuffer:统计每个 bucket 的消息数
    buf_lines: list[str] = []
    buf_total_msgs = 0
    if _mcp.message_buffer is not None:
        for key in _mcp.message_buffer.known_groups():
            bucket = _mcp.message_buffer._buckets.get(key)  # noqa: SLF001
            if bucket is not None:
                count = len(bucket)
                buf_total_msgs += count
                buf_lines.append(f"  - {key[0]}/{key[1]}: {count}")

    # BotRegistry:统计已知路由
    reg_lines: list[str] = []
    reg_count = 0
    if _mcp.bot_registry is not None:
        for k in _mcp.bot_registry.known():
            reg_count += 1
            reg_lines.append(f"  - {k[0]}/{k[1]}/{k[2]}")

    lines = [
        "🔍 Hermes Plugin M1-mem 状态",
        f"MCP: {mcp_line}",
        f"active_session: {active_line}",
        f"structured_path: {plugin_config.hermes_structured_path}",
        f"hermes_api: {plugin_config.hermes_api_url}",
        "",
        f"📊 ActiveSessions: {active_count} 个活跃",
    ]
    lines.extend(active_details[:10])  # 最多 10 个
    if len(active_details) > 10:
        lines.append(f"  ... +{len(active_details) - 10} more")

    lines.extend(
        [
            "",
            f"💬 MessageBuffer: {buf_total_msgs} 条 / {len(buf_lines)} 个 bucket",
        ]
    )
    lines.extend(buf_lines[:5])
    if len(buf_lines) > 5:
        lines.append(f"  ... +{len(buf_lines) - 5} more")

    lines.extend(
        [
            "",
            f"🤖 BotRegistry: {reg_count} 个路由",
        ]
    )
    lines.extend(reg_lines[:5])
    if len(reg_lines) > 5:
        lines.append(f"  ... +{len(reg_lines) - 5} more")

    await alconna.UniMessage("\n".join(lines)).send(target=target, bot=bot)
