"""(adapter, scope, scope_id) → (Bot, Target) 的内存路由表。

Target 永远不序列化:重启即清,首次 perception 事件重新填表。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class BotEntry:
    bot_self_id: str
    target: Any  # nonebot_plugin_alconna.Target,只存内存
    last_seen_at: int  # ms


class BotRegistry:
    def __init__(self) -> None:
        self._entries: Dict[Tuple[str, str, str], BotEntry] = {}

    def upsert(
        self,
        adapter: str,
        scope: str,  # "private" | "group"
        scope_id: str,
        bot_self_id: str,
        target: Any,
        ts: int,
    ) -> None:
        self._entries[(adapter, scope, scope_id)] = BotEntry(
            bot_self_id=bot_self_id,
            target=target,
            last_seen_at=ts,
        )

    def get(self, adapter: str, scope: str, scope_id: str) -> Optional[BotEntry]:
        return self._entries.get((adapter, scope, scope_id))

    def remove(self, adapter: str, scope: str, scope_id: str) -> None:
        self._entries.pop((adapter, scope, scope_id), None)

    def known(self, adapter: Optional[str] = None) -> List[Tuple[str, str, str]]:
        if adapter is None:
            return list(self._entries.keys())
        return [k for k in self._entries.keys() if k[0] == adapter]
