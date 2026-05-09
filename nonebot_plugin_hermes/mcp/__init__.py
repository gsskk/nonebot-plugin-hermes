"""nonebot-bridge MCP server 启动钩子。"""

from __future__ import annotations

import asyncio
from typing import Optional

import uvicorn
from nonebot import get_driver, logger

from ..config import plugin_config
from ..core.active_session import ActiveSessionManager
from ..core.bot_registry import BotRegistry
from ..core.message_buffer import MessageBuffer
from .server import build_mcp_app

# 全局单例(Task 18 在 plugin __init__.py 装配)
message_buffer: MessageBuffer | None = None
active_sessions: ActiveSessionManager | None = None
bot_registry: BotRegistry | None = None

_server_task: Optional[asyncio.Task] = None
_uvicorn_server: Optional[uvicorn.Server] = None


def init_runtime_state() -> None:
    """由 plugin __init__.py 在 import 时调用,装配三个全局对象。"""
    global message_buffer, active_sessions, bot_registry
    if message_buffer is None:
        message_buffer = MessageBuffer(
            per_group_cap=plugin_config.hermes_buffer_per_group_cap,
            total_groups_cap=plugin_config.hermes_buffer_total_groups_cap,
        )
    if active_sessions is None:
        active_sessions = ActiveSessionManager(
            default_ttl_sec=plugin_config.hermes_active_session_ttl_sec,
        )
    if bot_registry is None:
        bot_registry = BotRegistry()


def _on_server_task_done(task: asyncio.Task) -> None:
    """uvicorn.serve() 在 task 里跑;端口绑定失败 / 中途异常都在这里捕获。
    没有这个 callback 的话,asyncio 只会以 'Task exception was never retrieved'
    打到 stderr,我们的应用日志却以为已 'started'。"""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"[HERMES MCP] server task died: {exc!r}")


async def start_mcp_server() -> None:
    global _server_task, _uvicorn_server

    if not plugin_config.hermes_mcp_enabled:
        logger.info("[HERMES MCP] disabled (HERMES_MCP_ENABLED=false)")
        return
    if _server_task is not None and not _server_task.done():
        logger.warning("[HERMES MCP] start_mcp_server called twice; ignoring second call")
        return
    if message_buffer is None or active_sessions is None or bot_registry is None:
        logger.error("[HERMES MCP] runtime state not initialized; skipping")
        return

    asgi_app = build_mcp_app(
        message_buffer=message_buffer,
        active_sessions=active_sessions,
        bot_registry=bot_registry,
    )

    config = uvicorn.Config(
        asgi_app,
        host=plugin_config.hermes_mcp_host,
        port=plugin_config.hermes_mcp_port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    _uvicorn_server = server
    _server_task = asyncio.create_task(server.serve(), name="hermes-mcp-server")
    _server_task.add_done_callback(_on_server_task_done)
    # 注:create_task 立刻返回,uvicorn 还在异步绑定端口;此 log 仅声明意图,
    # 真正起来 / 失败由 _on_server_task_done 捕获或 uvicorn 自身 stderr 日志反映。
    logger.info(f"[HERMES MCP] starting on {plugin_config.hermes_mcp_host}:{plugin_config.hermes_mcp_port}")


async def stop_mcp_server() -> None:
    global _server_task, _uvicorn_server
    if _uvicorn_server is not None:
        _uvicorn_server.should_exit = True
    if _server_task is not None:
        forced = False
        try:
            # asyncio.wait_for 内部已在超时时取消 task,无需再 cancel
            await asyncio.wait_for(_server_task, timeout=5)
        except asyncio.TimeoutError:
            forced = True
        if forced:
            logger.warning("[HERMES MCP] graceful stop timed out; uvicorn was force-cancelled")
        else:
            logger.info("[HERMES MCP] stopped")
        _server_task = None
    _uvicorn_server = None


def register_lifecycle() -> None:
    """注册 nonebot 启动 / 停止钩子。"""
    driver = get_driver()
    driver.on_startup(start_mcp_server)
    driver.on_shutdown(stop_mcp_server)
