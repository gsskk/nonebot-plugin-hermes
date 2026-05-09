"""群活跃态(reactive 模式)的内存状态机。

每 (adapter, group_id) 至多一条活跃记录;TTL 滑动续期。
重启即清。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class ActiveSession:
    adapter: str
    group_id: str
    triggered_by: str
    started_at: int  # ms
    last_active_at: int  # ms
    expires_at: int  # ms
    topic_hint: Optional[str] = None


class ActiveSessionManager:
    """滑动 TTL 状态机,跟踪哪些 (adapter, group_id) 处于 reactive 监听窗口。

    线程安全:**否**。预设单线程 asyncio 事件循环,不要从背景线程访问。
    GC 策略:不在读路径自动剔除过期 session,由 Task 16 的 cron 调 sweep_expired()
    定期清理。读 API 中:`is_active` / `touch` / `get_if_active` 是 TTL 感知的;
    `get()` 是裸访问,**返回过期 session**——仅用于调试 / 日志,handler 应优先用
    is_active / get_if_active。
    """

    def __init__(self, default_ttl_sec: int = 300) -> None:
        self._ttl_ms = default_ttl_sec * 1000
        self._sessions: Dict[Tuple[str, str], ActiveSession] = {}

    def trigger(
        self,
        adapter: str,
        group_id: str,
        user_id: str,
        now_ms: int,
        topic_hint: Optional[str] = None,
    ) -> ActiveSession:
        s = ActiveSession(
            adapter=adapter,
            group_id=group_id,
            triggered_by=user_id,
            started_at=now_ms,
            last_active_at=now_ms,
            expires_at=now_ms + self._ttl_ms,
            topic_hint=topic_hint,
        )
        self._sessions[(adapter, group_id)] = s
        return s

    def touch(self, adapter: str, group_id: str, now_ms: int) -> Optional[ActiveSession]:
        s = self._sessions.get((adapter, group_id))
        if s is None or s.expires_at <= now_ms:
            return None
        s.last_active_at = now_ms
        s.expires_at = now_ms + self._ttl_ms
        return s

    def get(self, adapter: str, group_id: str) -> Optional[ActiveSession]:
        """裸访问,**不检查 TTL**——可能返回已过期 session。

        多数 handler 应改用 `get_if_active` 或先 `is_active` 校验。本方法保留是为了
        调试 / 日志场景需要观测已过期但尚未被 sweep 的 session。
        """
        return self._sessions.get((adapter, group_id))

    def get_if_active(self, adapter: str, group_id: str, now_ms: int) -> Optional[ActiveSession]:
        """TTL 感知的 get:只在 session 存在且未过期时返回。"""
        s = self._sessions.get((adapter, group_id))
        if s is None or s.expires_at <= now_ms:
            return None
        return s

    def is_active(self, adapter: str, group_id: str, now_ms: int) -> bool:
        s = self._sessions.get((adapter, group_id))
        return s is not None and s.expires_at > now_ms

    def update_topic(self, adapter: str, group_id: str, topic_hint: Optional[str]) -> None:
        """更新或清空 topic_hint。

        传 None 即清空(允许 Hermes 在话题漂移检测后主动收尾 topic)。
        若 (adapter, group_id) 不存在则 no-op。
        """
        s = self._sessions.get((adapter, group_id))
        if s is not None:
            s.topic_hint = topic_hint

    def end(self, adapter: str, group_id: str) -> None:
        self._sessions.pop((adapter, group_id), None)

    def list(self, adapter: Optional[str] = None) -> List[ActiveSession]:
        if adapter is None:
            return list(self._sessions.values())
        return [s for s in self._sessions.values() if s.adapter == adapter]

    def sweep_expired(self, now_ms: int) -> List[ActiveSession]:
        expired = [s for s in self._sessions.values() if s.expires_at <= now_ms]
        for s in expired:
            self._sessions.pop((s.adapter, s.group_id), None)
        return expired
