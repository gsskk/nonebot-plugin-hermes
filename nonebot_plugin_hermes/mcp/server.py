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

    # 注:三个工具的签名都是扁平参数(非 Pydantic model 包装)。FastMCP 单 model 入参
    # 会把 schema 暴露成 {properties: {input: {...}}},逼客户端 wrap 一层 input,
    # 调用方传扁平参数会撞上"Missing required argument 'input'"+"Unexpected
    # keyword argument 'adapter/group_id/...'"的混淆错误。扁平签名让 schema 直接
    # 是 {adapter, group_id, ...},LLM 自然写法和 curl 默认形态都对得上。
    # Input 模型保留:它是 impl 层契约 + 单元测试入口。

    @mcp.tool()
    async def push_message(
        adapter: str,
        group_id: str,
        text: str,
        image_urls: list[str] | None = None,
        reply_to_msg_id: str | None = None,
        task_id: str | None = None,
    ) -> PushMessageResult:
        """Send a message to a group via nonebot. Reactive context required."""
        inp = PushMessageInput(
            adapter=adapter,
            group_id=group_id,
            text=text,
            image_urls=image_urls or [],
            reply_to_msg_id=reply_to_msg_id,
            task_id=task_id,
        )
        return await push_message_impl(
            inp,
            active_sessions=active_sessions,
            bot_registry=bot_registry,
        )

    @mcp.tool()
    async def list_active_sessions(
        adapter: str | None = None,
    ) -> ListActiveSessionsResult:
        """List active reactive sessions."""
        inp = ListActiveSessionsInput(adapter=adapter)
        return await list_active_sessions_impl(inp, active_sessions=active_sessions)

    @mcp.tool()
    async def get_recent_messages(
        adapter: str,
        group_id: str,
        limit: int = 20,
        before_ts: int | None = None,
    ) -> GetRecentMessagesResult:
        """Fetch recent messages from a group's buffer. Use sparingly."""
        inp = GetRecentMessagesInput(
            adapter=adapter,
            group_id=group_id,
            limit=limit,
            before_ts=before_ts,
        )
        return await get_recent_messages_impl(inp, message_buffer=message_buffer)

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

    # 注:lifespan 通过上面 `scope["type"] != "http"` 分支自然 passthrough 到 http_app,
    # FastMCP 的启动钩子在 inner app 里被 uvicorn 直接以 lifespan scope 调到。
    # 不需要也不应在这里设置 .lifespan 属性——uvicorn 不读这个属性。
    return bearer_middleware
