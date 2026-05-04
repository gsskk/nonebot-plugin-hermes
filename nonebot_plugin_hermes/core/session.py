"""
会话管理

维护 session key 映射，会话生命周期由 Hermes Agent 的 reset policy 管理。
"""

from __future__ import annotations

from typing import Optional, Dict, Tuple, List
from collections import deque


from nonebot import logger

from ..config import plugin_config


class SessionManager:
    """管理 Hermes session key 的生成和过期"""

    def __init__(self):
        # key: internal_session_id -> value: hermes session key
        self._cache: dict[str, str] = {}
        # 跟踪每个 session 的生成时间戳，用于 /clear 重置
        self._generation: dict[str, int] = {}
        # 记录最近的聊天上下文 (Passive Perception)
        # key: internal_id -> value: deque of (sender_name, content)
        self._history: Dict[str, deque] = {}

    def _get_internal_id(
        self,
        adapter_name: str,
        is_private: bool,
        user_id: str,
        group_id: Optional[str] = None,
    ) -> str:
        """根据配置生成统一的内部会话 ID"""
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
        """获取或创建 Hermes session key。"""
        internal_id = self._get_internal_id(adapter_name, is_private, user_id, group_id)

        cached = self._cache.get(internal_id)
        if cached is not None:
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
        """重置会话"""
        internal_id = self._get_internal_id(adapter_name, is_private, user_id, group_id)

        # 从缓存中移除
        self._cache.pop(internal_id, None)
        # 清除历史记录
        self._history.pop(internal_id, None)

        # 递增 generation
        gen = self._generation.get(internal_id, 0) + 1
        self._generation[internal_id] = gen

        logger.info(f"[SESSION] 会话已重置: {internal_id} (generation={gen})")

    def record_history(
        self,
        adapter_name: str,
        is_private: bool,
        user_id: str,
        group_id: Optional[str],
        sender_name: str,
        content: str,
        image_urls: Optional[List[str]] = None,
    ) -> None:
        """记录一条历史消息到缓冲区"""
        if not plugin_config.hermes_perception_enabled or is_private:
            return

        internal_id = self._get_internal_id(adapter_name, is_private, user_id, group_id)

        if internal_id not in self._history:
            self._history[internal_id] = deque(maxlen=plugin_config.hermes_perception_buffer)

        # 限制单条消息长度
        max_len = plugin_config.hermes_perception_text_length
        if len(content) > max_len:
            content = content[:max_len] + "..."

        # 存储内容为 (发送者, 文本, 图片列表)
        self._history[internal_id].append((sender_name, content, image_urls or []))

    def get_history_context(
        self,
        adapter_name: str,
        is_private: bool,
        user_id: str,
        group_id: Optional[str],
    ) -> Tuple[str, List[str]]:
        """获取格式化后的历史背景文本以及需要包含的历史图片 URL"""
        if not plugin_config.hermes_perception_enabled or is_private:
            return "", []

        internal_id = self._get_internal_id(adapter_name, is_private, user_id, group_id)
        history = self._history.get(internal_id)
        if not history:
            return "", []

        lines = [
            "--- RECENT CHAT HISTORY (FOR AWARENESS ONLY) ---",
            "The following messages are provided so you are aware of the recent conversation you were not part of. Do not proactively respond to these unless directly relevant to the current user's request.",
        ]
        extra_images = []
        all_history_images = []

        for sender, content, imgs in history:
            lines.append(f"{sender}: {content}")
            all_history_images.extend(imgs)

        lines.append("--- END OF HISTORY ---")

        # 处理 'last' 模式：提取最后一张真图
        if plugin_config.hermes_perception_image_mode == "last" and all_history_images:
            extra_images = [all_history_images[-1]]

        return "\n".join(lines), extra_images


# 全局会话管理器
session_manager = SessionManager()
