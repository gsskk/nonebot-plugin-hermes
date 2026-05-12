"""In-flight 调用追踪 + coalesce 重燃支持。

修同一 (adapter, group_id|user_id) 上事件 task 并发调 chat() 的 bug:
in-flight 时新消息只更新 pending 单元,等当前一发完成后再合并跑一次。

线程安全:**否**。预设单线程 asyncio 事件循环,与 ActiveSessionManager 一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Optional, Tuple

from .message_buffer import BufferedMessage


# Refire 链最大深度。超过则丢 pending、warn,等下一个新触发。
# 一次 burst 最多产出 1(主回) + MAX_REFIRE_DEPTH(链尾)= 4 发回复。
MAX_REFIRE_DEPTH = 3


@dataclass
class InflightSlot:
    started_at: int
    pending: Optional[BufferedMessage] = None


class InflightRegistry:
    """per-target 非阻塞 busy 标记 + pending 单元。

    Key 约定:
      - 群: ("adapter", "group:" + group_id)
      - 私聊: ("adapter", "private:" + user_id)

    不持有任何 asyncio.Task 引用 —— 重燃由 caller 用 create_task 自己接手,
    registry 只负责「现在有没有人在跑」+「跑完后是否要再跑一次」两个状态。
    """

    def __init__(self) -> None:
        self._slots: Dict[Tuple[str, str], InflightSlot] = {}

    def try_enter(
        self,
        key: Tuple[str, str],
        current_msg: BufferedMessage,
        now_ms: int,
    ) -> Literal["entered", "pending_set"]:
        """无 slot → 占位 started_at=now_ms,返回 'entered'。
        有 slot → 把 current_msg 写进 pending(覆盖旧 pending),返回 'pending_set'。
        """
        slot = self._slots.get(key)
        if slot is None:
            self._slots[key] = InflightSlot(started_at=now_ms)
            return "entered"
        slot.pending = current_msg
        return "pending_set"

    def take_pending(self, key: Tuple[str, str]) -> Optional[BufferedMessage]:
        """Destructive read。无 slot 或 pending 为 None 都返回 None。"""
        slot = self._slots.get(key)
        if slot is None:
            return None
        msg = slot.pending
        slot.pending = None
        return msg

    def exit(self, key: Tuple[str, str]) -> None:
        """释放 slot。pending 仍在的话由调用方自行先 take_pending。
        slot 不存在则 no-op。
        """
        self._slots.pop(key, None)
