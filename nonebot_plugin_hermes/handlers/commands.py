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
# --- /hermes-label ---
# /hermes-label 命令族 (0.5.0+):
#   add <tag>           — 给当前 session 加 1 个 tag
#   remove <tag>        — 删 1 个 tag
#   list                — 列当前 session 的所有 tags + priority + note
#   find <tag>          — 找同 tag 的 session
#   priority <0-3>      — 设优先级
#   note <text>         — 设备注(空 = 清)
#   clear               — 清空所有标注(保留真 title)
#   rebuild             — 管理员:从 gateway 拉全部 session 重建本地索引

from ..core.session_label import (  # noqa: E402
    Annotations,
    decode_annotations,
    encode_annotations,
    label_index,
)

label_command = on_command(
    "hermes-label", aliases={"标签"}, force_whitespace=True, priority=88, block=True
)


def _is_label_admin(target, user_id: str) -> bool:
    """检查当前用户是否被允许使用 /hermes-label 命令。"""
    if not plugin_config.hermes_label_admin_only:
        return True
    adapter_name = get_adapter_name(target)
    return f"{adapter_name}:{user_id}" in plugin_config.hermes_admin_users


def _current_session_key(adapter_name: str, is_private: bool, user_id: str, group_id):
    """复用 session_manager 拿到当前 session_key(X-Hermes-Session-Id header 值)。"""
    return session_manager.get_session_key(
        adapter_name=adapter_name,
        is_private=is_private,
        user_id=user_id,
        group_id=group_id,
    )


@label_command.handle()
async def handle_label(bot: Bot, event: Event, matcher: Matcher):
    """/hermes-label 主入口。"""
    target = alconna.get_target()
    if not check_isolation(event, target):
        matcher.skip()

    if not plugin_config.hermes_label_enabled:
        await alconna.UniMessage(
            "⚠️ /hermes-label 未启用, 请在 .env 设置 HERMES_LABEL_ENABLED=true"
        ).send(target=target, bot=bot)
        return

    raw = event.get_plaintext().strip()
    for prefix in ("/hermes-label ", "/hermes-label", "标签 ", "标签"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
            break
    parts = raw.split(maxsplit=1)
    if not parts:
        await alconna.UniMessage(
            "用法:\n"
            "/hermes-label add <tag>\n"
            "/hermes-label remove <tag>\n"
            "/hermes-label list\n"
            "/hermes-label find <tag>\n"
            "/hermes-label priority <0-3>\n"
            "/hermes-label note <text>\n"
            "/hermes-label clear\n"
            "/hermes-label rebuild (admin)"
        ).send(target=target, bot=bot)
        return

    subcmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    adapter_name = get_adapter_name(target)
    user_id = event.get_user_id() or ""
    is_private = target.private
    group_id = None if is_private else target.id

    if subcmd == "rebuild":
        if not _is_label_admin(target, user_id):
            return
        await _do_rebuild(target, bot)
        return

    current_key = _current_session_key(adapter_name, is_private, user_id, group_id)

    if subcmd in ("add", "remove", "priority", "note", "clear"):
        if not _is_label_admin(target, user_id):
            return
    elif subcmd == "find":
        if not _is_label_admin(target, user_id):
            return

    if subcmd == "add":
        if not arg:
            await alconna.UniMessage("用法: /hermes-label add <tag>").send(target=target, bot=bot)
            return
        await _do_modify(target, bot, current_key, "add", arg)
    elif subcmd == "remove":
        if not arg:
            await alconna.UniMessage("用法: /hermes-label remove <tag>").send(target=target, bot=bot)
            return
        await _do_modify(target, bot, current_key, "remove", arg)
    elif subcmd == "priority":
        if not arg.isdigit() or not (0 <= int(arg) <= 3):
            await alconna.UniMessage("用法: /hermes-label priority <0-3>").send(target=target, bot=bot)
            return
        await _do_modify(target, bot, current_key, "priority", int(arg))
    elif subcmd == "note":
        await _do_modify(target, bot, current_key, "note", arg)
    elif subcmd == "clear":
        await _do_modify(target, bot, current_key, "clear", "")
    elif subcmd == "list":
        await _do_list(target, bot, current_key)
    elif subcmd == "find":
        if not arg:
            await alconna.UniMessage("用法: /hermes-label find <tag>").send(target=target, bot=bot)
            return
        await _do_find(target, bot, arg)
    else:
        await alconna.UniMessage(f"⚠️ 未知子命令: {subcmd}").send(target=target, bot=bot)


async def _do_modify(target, bot, session_key: str, op: str, value):
    """add/remove/priority/note/clear 的统一实现。"""
    session = await hermes_client.get_session(session_key)
    if session is None:
        await alconna.UniMessage(f"⚠️ 找不到 session: {session_key}").send(target=target, bot=bot)
        return

    old_title = session.get("title") or ""
    ann, real_title = decode_annotations(old_title)
    labels = list(ann.labels)
    priority = ann.priority
    note = ann.note

    if op == "add":
        if value in labels:
            await alconna.UniMessage(f"⚠️ 标签已存在: {value}").send(target=target, bot=bot)
            return
        labels.append(value)
    elif op == "remove":
        if value not in labels:
            await alconna.UniMessage(f"⚠️ 标签不存在: {value}").send(target=target, bot=bot)
            return
        labels.remove(value)
    elif op == "priority":
        priority = value
    elif op == "note":
        note = value or None
    elif op == "clear":
        labels, priority, note = [], 0, None

    new_ann = Annotations(labels=labels, priority=priority, note=note)
    new_title = encode_annotations(real_title=real_title, annotations=new_ann)
    ok = await hermes_client.patch_session_title(session_key, new_title)
    if not ok:
        await alconna.UniMessage("⚠️ 写入失败, gateway 拒绝了 PATCH").send(target=target, bot=bot)
        return
    label_index.set(session_key, new_ann)
    await alconna.UniMessage(
        f"✅ session {session_key[:16]}... 标注已更新:\n"
        f"  labels: {new_ann.labels}\n"
        f"  priority: {new_ann.priority}\n"
        f"  note: {new_ann.note or '(无)'}"
    ).send(target=target, bot=bot)


async def _do_list(target, bot, session_key: str):
    """列当前 session 的标注。"""
    session = await hermes_client.get_session(session_key)
    if session is None:
        await alconna.UniMessage(f"⚠️ 找不到 session: {session_key}").send(target=target, bot=bot)
        return
    ann, real_title = decode_annotations(session.get("title"))
    label_index.set(session_key, ann)
    lines = [
        f"📋 session {session_key[:16]}... 标注:",
        f"  title: {real_title or '(空)'}",
        f"  labels: {ann.labels or '(无)'}",
        f"  priority: {ann.priority}",
        f"  note: {ann.note or '(无)'}",
    ]
    await alconna.UniMessage("\n".join(lines)).send(target=target, bot=bot)


async def _do_find(target, bot, label: str):
    """管理员:查同 tag 的 session。"""
    session_keys = label_index.find_by_label(label)
    if not session_keys:
        await alconna.UniMessage(
            f"🏷️ 本地索引里没找到标签: {label}\n(可以试试 /hermes-label rebuild)"
        ).send(target=target, bot=bot)
        return
    lines = [f"🏷️ 标签 '{label}' 命中 {len(session_keys)} 个 session:"]
    for sk in session_keys[:20]:
        ann = label_index.get(sk)
        if ann:
            lines.append(f"  - {sk[:20]}... priority={ann.priority} labels={ann.labels}")
    if len(session_keys) > 20:
        lines.append(f"  ... +{len(session_keys) - 20} more")
    await alconna.UniMessage("\n".join(lines)).send(target=target, bot=bot)


async def _do_rebuild(target, bot):
    """管理员:从 gateway 拉全部 session 重建本地索引。"""
    sessions = await hermes_client.list_sessions(limit=200)
    label_index.clear()
    n_labeled = 0
    for s in sessions:
        sid = s.get("id") or s.get("session_id")
        if not sid:
            continue
        ann, _ = decode_annotations(s.get("title"))
        if ann.labels or ann.priority or ann.note:
            label_index.set(sid, ann)
            n_labeled += 1
    await alconna.UniMessage(
        f"🔄 重建索引完成: 扫了 {len(sessions)} 个 session, 其中 {n_labeled} 个带标注"
    ).send(target=target, bot=bot)
