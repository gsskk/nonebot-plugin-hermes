"""nonebot-bridge MCP server 启动钩子。"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import uvicorn
from nonebot import get_driver, logger

from ..config import plugin_config
from ..core.active_session import ActiveSessionManager
from ..core.bot_registry import BotRegistry
from ..core.inflight import InflightRegistry
from ..core.message_buffer import MessageBuffer
from .server import build_mcp_app


class _ToolValidationLogRedirect(logging.Filter):
    """把 FastMCP 'Error validating tool' 日志 drop 掉,用 nonebot logger 重发一行。

    FastMCP 在 server.py 对客户端参数校验失败用 logger.exception() 打成
    ERROR + 完整栈,但这其实是 *客户端错*——错误已通过 structured response
    (isError=true) 回给调用方了,服务端再打满屏 traceback 看起来像 server
    crash 但不是。
    丢弃原 stdlib record,通过 nonebot 的 loguru logger 发一行简洁 WARNING,
    与 bot 其它日志格式对齐(右对齐时间戳 / 颜色 / 文件位置)。
    其它真实异常路径('Error calling tool ...')不在前缀范围内,保持原样。
    """

    _PREFIX = "Error validating tool "
    _TOOL_RE = re.compile(r"^Error validating tool '([^']+)'")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if not msg.startswith(self._PREFIX):
            return True

        m = self._TOOL_RE.match(msg)
        tool_name = m.group(1) if m else "?"

        detail = ""
        if record.exc_info and record.exc_info[1] is not None:
            # ValidationError str 多行,collapse 成一行并截断
            detail = str(record.exc_info[1]).replace("\n", " | ")[:200]

        logger.warning(
            f"[HERMES MCP] tool '{tool_name}' validation failed: {detail}"
            if detail
            else f"[HERMES MCP] tool '{tool_name}' validation failed (no detail)"
        )
        return False  # 丢弃原 stdlib record


# 模块级安装一次。fastmcp 用 logging.getLogger("fastmcp.server.server"),
# import 期 attach filter,所有后续 record 都过这条。
_FASTMCP_TOOL_LOGGER = logging.getLogger("fastmcp.server.server")
if not any(isinstance(f, _ToolValidationLogRedirect) for f in _FASTMCP_TOOL_LOGGER.filters):
    _FASTMCP_TOOL_LOGGER.addFilter(_ToolValidationLogRedirect())

# 全局单例(Task 18 在 plugin __init__.py 装配)
message_buffer: MessageBuffer | None = None
active_sessions: ActiveSessionManager | None = None
bot_registry: BotRegistry | None = None
inflight: InflightRegistry | None = None

_server_task: Optional[asyncio.Task] = None
_uvicorn_server: Optional[uvicorn.Server] = None


def init_runtime_state() -> None:
    """由 plugin __init__.py 在 import 时调用,装配全局对象。"""
    global message_buffer, active_sessions, bot_registry, inflight
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
    if inflight is None:
        inflight = InflightRegistry()


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
