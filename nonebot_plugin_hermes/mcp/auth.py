"""MCP 鉴权 + 工具上下文校验。

两个层次:
  1. HTTP 层 Bearer:check_bearer(authorization_header, expected)
  2. 工具层 push_message 上下文:validate_push_context(...)
"""

from __future__ import annotations

import hmac
from typing import Optional

from ..core.active_session import ActiveSessionManager
from ..core.bot_registry import BotRegistry


class AuthError(Exception):
    """HTTP 层鉴权失败,应映射成 401。"""


class PushContextError(Exception):
    """push_message 工具上下文不满足,应映射成 422。"""


def check_bearer(authorization_header: Optional[str], expected: str) -> None:
    """HTTP 层 Bearer 校验。

    Args:
        authorization_header: Request 头中 Authorization 字段值,或 None。
        expected: 期望的 token。**空字符串 = 开发模式,完全跳过校验**——
            参数类型为 str 而非 Optional[str],防未来 config 类型变 Optional[str]
            时 None 触发 falsy 静默 bypass。

    Raises:
        AuthError: header 缺失 / scheme 错 / token 不匹配。
    """
    # 注:expected="" 是开发模式约定,与 hermes_api_key 同口径。
    if not expected:
        return
    if not authorization_header:
        raise AuthError("missing Authorization header")
    parts = authorization_header.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("expected scheme Bearer")
    # 容忍尾部空白:客户端偶有意外空格,这里 strip 后再常时间比较
    if not hmac.compare_digest(parts[1].strip(), expected):
        raise AuthError("token mismatch")


def validate_push_context(
    *,
    adapter: str,
    group_id: str,
    active_sessions: ActiveSessionManager,
    bot_registry: BotRegistry,
    now_ms: int,
) -> None:
    """守卫 push_message MCP 工具调用的前置上下文。

    M1 规则:必须存在 (adapter, group_id) 的活跃 reactive session,
    且 BotRegistry 有对应路由(target+bot_self_id)才允许 push。
    检查顺序:先 session 后 target——session 缺失更常见(TTL 过期),
    优先报这条更直观。

    M2 将增加 bg_task 路径(执行中的任务允许 push 即使无 reactive session)。

    Raises:
        PushContextError: 任一前置不满足;调用方映射 HTTP 422。
    """
    if not active_sessions.is_active(adapter, group_id, now_ms):
        raise PushContextError(f"no active reactive session for ({adapter}, {group_id})")
    if bot_registry.get(adapter, "group", group_id) is None:
        raise PushContextError(f"unknown target ({adapter}, {group_id}) — wait for next group message to repopulate")
