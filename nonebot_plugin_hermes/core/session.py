"""
会话管理

使用 TTLCache 维护 session key 映射，支持会话过期自动重置。
"""

from __future__ import annotations

from typing import Optional

from cachetools import TTLCache
from nonebot import logger

from ..config import plugin_config


class SessionManager:
    """管理 Hermes session key 的生成和过期"""

    def __init__(self, ttl: int = 3600, maxsize: int = 4096):
        # key: internal_session_id -> value: hermes session key (带时间戳后缀)
        self._cache: TTLCache[str, str] = TTLCache(maxsize=maxsize, ttl=ttl)
        # 跟踪每个 session 的生成时间戳，用于 /clear 重置
        self._generation: dict[str, int] = {}

    def get_session_key(
        self,
        adapter_name: str,
        is_private: bool,
        user_id: str,
        group_id: Optional[str] = None,
    ) -> str:
        """获取或创建 Hermes session key。

        Session key 格式: hermes-{adapter}-{private|group}-{id}[-{gen}]

        Args:
            adapter_name: 适配器名称 (onebot11, qqbot, etc.)
            is_private: 是否私聊
            user_id: 用户 ID
            group_id: 群组 ID（群聊时）

        Returns:
            Hermes session key string
        """
        if is_private:
            internal_id = f"{adapter_name}+private+{user_id}"
        elif plugin_config.hermes_session_share_group and group_id:
            # 群组共享 session
            internal_id = f"{adapter_name}+group+{group_id}"
        else:
            # 每人独立 session
            internal_id = f"{adapter_name}+group+{group_id or 'unknown'}+{user_id}"

        cached = self._cache.get(internal_id)
        if cached is not None:
            # 刷新 TTL
            self._cache[internal_id] = cached
            return cached

        # 生成新的 session key
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
        """重置会话（通过递增 generation 使下次生成新 session key）"""
        if is_private:
            internal_id = f"{adapter_name}+private+{user_id}"
        elif plugin_config.hermes_session_share_group and group_id:
            internal_id = f"{adapter_name}+group+{group_id}"
        else:
            internal_id = f"{adapter_name}+group+{group_id or 'unknown'}+{user_id}"

        # 从缓存中移除
        self._cache.pop(internal_id, None)

        # 递增 generation
        gen = self._generation.get(internal_id, 0) + 1
        self._generation[internal_id] = gen

        logger.info(f"[SESSION] 会话已重置: {internal_id} (generation={gen})")


# 全局会话管理器
session_manager = SessionManager(ttl=plugin_config.hermes_session_expire)
