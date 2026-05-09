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
    """HTTP 层 Bearer 校验。expected 为空时跳过(开发模式)。"""
    if not expected:
        return
    if not authorization_header:
        raise AuthError("missing Authorization header")
    parts = authorization_header.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("expected scheme Bearer")
    if not hmac.compare_digest(parts[1], expected):
        raise AuthError("token mismatch")


def validate_push_context(
    *,
    adapter: str,
    group_id: str,
    active_sessions: ActiveSessionManager,
    bot_registry: BotRegistry,
    now_ms: int,
) -> None:
    """M1: 仅 reactive 分支。bg_tasks 在 M2 引入。"""
    if not active_sessions.is_active(adapter, group_id, now_ms):
        raise PushContextError(f"no active reactive session for ({adapter}, {group_id})")
    if bot_registry.get(adapter, "group", group_id) is None:
        raise PushContextError(f"unknown target ({adapter}, {group_id}) — wait for next group message to repopulate")
