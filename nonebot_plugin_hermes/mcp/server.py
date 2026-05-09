"""FastMCP app 工厂。

把 push_message / list_active_sessions / get_recent_messages 三个工具
装配进一个 FastMCP 实例,供 mcp/__init__.py 启动 uvicorn 时使用。
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from starlette.responses import JSONResponse

from ..config import plugin_config
from ..core.active_session import ActiveSessionManager
from ..core.bot_registry import BotRegistry
from ..core.message_buffer import MessageBuffer
from .auth import AuthError, check_bearer
from .tools.get_recent_messages import (
    GetRecentMessagesInput,
    GetRecentMessagesResult,
    get_recent_messages_impl,
)
from .tools.list_active_sessions import (
    ListActiveSessionsInput,
    ListActiveSessionsResult,
    list_active_sessions_impl,
)
from .tools.push_message import (
    PushMessageInput,
    PushMessageResult,
    push_message_impl,
)


def build_mcp_app(
    *,
    message_buffer: MessageBuffer,
    active_sessions: ActiveSessionManager,
    bot_registry: BotRegistry,
) -> Any:
    """构造 FastMCP 实例并返回 http_app(),由调用者交给 uvicorn。

    fastmcp 3.x: `http_app()` 替代旧版 `streamable_http_app()`。
    返回 Starlette ASGI app,我们在外面再包一层 Bearer 鉴权中间件。
    """

    mcp = FastMCP("nonebot-bridge")

    @mcp.tool()
    async def push_message(input: PushMessageInput) -> PushMessageResult:
        """Send a message to a group via nonebot. Reactive context required."""
        return await push_message_impl(
            input,
            active_sessions=active_sessions,
            bot_registry=bot_registry,
        )

    @mcp.tool()
    async def list_active_sessions(input: ListActiveSessionsInput) -> ListActiveSessionsResult:
        """List active reactive sessions."""
        return await list_active_sessions_impl(input, active_sessions=active_sessions)

    @mcp.tool()
    async def get_recent_messages(input: GetRecentMessagesInput) -> GetRecentMessagesResult:
        """Fetch recent messages from a group's buffer. Use sparingly."""
        return await get_recent_messages_impl(input, message_buffer=message_buffer)

    http_app = mcp.http_app()

    # Bearer 中间件 — 在 ASGI 层裹一层
    expected_token = plugin_config.hermes_api_key

    async def bearer_middleware(scope, receive, send):
        if scope["type"] != "http":
            return await http_app(scope, receive, send)
        headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
        try:
            check_bearer(headers.get("authorization"), expected_token)
        except AuthError as exc:
            response = JSONResponse({"error": str(exc)}, status_code=401)
            return await response(scope, receive, send)
        return await http_app(scope, receive, send)

    # 把内层 http_app 的 lifespan 暴露在外层,uvicorn 才会跑 FastMCP 的启动钩子
    bearer_middleware.lifespan = getattr(http_app, "lifespan", None)  # type: ignore[attr-defined]
    return bearer_middleware
