"""
会话管理

只维护 Hermes session key 映射;消息历史已移交 MessageBuffer。
"""

from __future__ import annotations

from typing import Any, Optional

from nonebot import logger

from ..config import plugin_config


class SessionManager:
    """管理 Hermes session key 的生成和过期"""

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._generation: dict[str, int] = {}

    def _get_internal_id(
        self,
        adapter_name: str,
        is_private: bool,
        user_id: str,
        group_id: Optional[str] = None,
    ) -> str:
        """根据配置生成统一的内部会话 ID。

        注:adapter_name / user_id / group_id 假定不含 '+';真实 adapter 名经
        get_adapter_name() 规整后均为 [a-z0-9],平台 user_id 多为数字串。
        """
        if is_private:
            return f"{adapter_name}+private+{user_id}"
        elif plugin_config.hermes_session_share_group and group_id:
            return f"{adapter_name}+group+{group_id}"
        else:
            return f"{adapter_name}+group+{group_id or 'unknown'}+{user_id}"

    def get_session_key(
        self,
        adapter_name: str,
        is_private: bool,
        user_id: str,
        group_id: Optional[str] = None,
    ) -> str:
        """获取或创建 Hermes session key,通过 X-Hermes-Session-Id 头送给上游。"""
        internal_id = self._get_internal_id(adapter_name, is_private, user_id, group_id)
        cached = self._cache.get(internal_id)
        if cached is not None:
            return cached

        gen = self._generation.get(internal_id, 0)
        session_key = f"hermes-{internal_id}"
        if gen > 0:
            session_key = f"{session_key}-g{gen}"

        self._cache[internal_id] = session_key
        logger.debug(f"[SESSION] 新建会话: {internal_id} -> {session_key}")
        return session_key

    def clear_session(
        self,
        adapter_name: str,
        is_private: bool,
        user_id: str,
        group_id: Optional[str] = None,
    ) -> None:
        """重置会话:递增 generation,使下次 get_session_key 返回新 key,
        Hermes 据此把后续对话当作新会话。"""
        internal_id = self._get_internal_id(adapter_name, is_private, user_id, group_id)
        self._cache.pop(internal_id, None)
        gen = self._generation.get(internal_id, 0) + 1
        self._generation[internal_id] = gen
        logger.info(f"[SESSION] 会话已重置: {internal_id} (generation={gen})")

    # === Task 15 之前的过渡桩 ===
    # handlers/message.py 仍调用下面两个方法。Task 15 重写 handlers 后删除这一段。
    # 桩返回安全的空值并 logger.warning,使中间状态可以 nb run 但 perception/历史功能失效可见。

    def record_history(self, *args: Any, **kwargs: Any) -> None:
        logger.warning(
            "[SESSION] record_history called but moved to MessageBuffer; "
            "Task 15 will rewire handlers/message.py — expect missing perception until then."
        )

    def get_history_context(self, *args: Any, **kwargs: Any) -> tuple[str, list[str]]:
        logger.warning(
            "[SESSION] get_history_context called but moved to MessageBuffer; "
            "Task 15 will rewire handlers/message.py — expect missing history until then."
        )
        return "", []


# 全局会话管理器
session_manager = SessionManager()
