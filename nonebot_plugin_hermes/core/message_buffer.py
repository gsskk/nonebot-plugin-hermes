"""内存消息缓冲。

替代 SQLite messages 表 + SessionManager._history。
重启即清,LRU 控制内存占用。
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple


@dataclass
class BufferedMessage:
    ts: int
    adapter: str
    group_id: Optional[str]  # None = 私聊
    user_id: str
    nickname: str
    content: str
    image_urls: List[str] = field(default_factory=list)
    reply_to_ts: Optional[int] = None
    is_bot: bool = False


def _bucket_key(adapter: str, group_id: Optional[str], user_id: Optional[str]) -> Tuple[str, str]:
    """私聊:用 user_id 作为 group 维度;群聊:用 group_id。"""
    if group_id is None:
        return (adapter, f"@private:{user_id or '?'}")
    return (adapter, group_id)


_PRIVATE_KEY_PREFIX = "@private:"


def is_private_key(key: Tuple[str, str]) -> bool:
    """判断 known_groups() 返回的 (adapter, scope_id) 是否为私聊桶。"""
    return key[1].startswith(_PRIVATE_KEY_PREFIX)


class MessageBuffer:
    """每 (adapter, group_id) 一个 deque,顶层 OrderedDict 做 LRU。

    LRU 策略:**写访问与读访问都更新位置**(read-promotes-LRU)。
    意味着只要某群被 append 或 get_recent,它就 stays in cache;最久未触碰的群被 evict。
    优点:正在被工具反复查询的群不会被淘汰。
    缺点:大量被动查询会 pin 住低活跃群——若 known_groups() 用于"挑活跃群推送"等场景,
    需要消费者自行用 last-write timestamp 过滤。
    """

    def __init__(self, per_group_cap: int = 200, total_groups_cap: int = 50) -> None:
        self._per_group_cap = per_group_cap
        self._total_groups_cap = total_groups_cap
        self._buckets: "OrderedDict[Tuple[str, str], Deque[BufferedMessage]]" = OrderedDict()

    def append(self, msg: BufferedMessage) -> None:
        key = _bucket_key(msg.adapter, msg.group_id, msg.user_id)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = deque(maxlen=self._per_group_cap)
            self._buckets[key] = bucket
            self._evict_if_needed()
        else:
            self._buckets.move_to_end(key)
        bucket.append(msg)

    def get_recent(
        self,
        adapter: str,
        group_id: Optional[str],
        limit: int,
        before_ts: Optional[int] = None,
        owner_user_id: Optional[str] = None,
    ) -> List[BufferedMessage]:
        """返回该群 / 该私聊的最近 N 条,**新 → 旧**顺序。

        owner_user_id: 仅在私聊取数时需要(group_id=None);群聊忽略。
        若 group_id=None 且 owner_user_id=None 会抛 ValueError——避免 Task 7/13/15
        集成时静默查询到空 bucket 而 debug 困难。
        """
        if group_id is None and owner_user_id is None:
            raise ValueError(
                "owner_user_id is required when group_id is None (private chat lookup); "
                "passing both as None silently misses every private bucket."
            )
        key = _bucket_key(adapter, group_id, owner_user_id)
        bucket = self._buckets.get(key)
        if not bucket:
            return []
        # 标记为最近访问(read-promotes-LRU,见 class docstring)
        self._buckets.move_to_end(key)
        items = list(bucket)
        if before_ts is not None:
            items = [m for m in items if m.ts < before_ts]
        items.reverse()
        return items[:limit]

    def known_groups(self) -> List[Tuple[str, str]]:
        """返回所有当前缓存中的 (adapter, scope_id)。

        scope_id 为群 id 或合成的 `@private:<user_id>`(用 is_private_key() 判别)。
        顺序:LRU 最旧 → 最新(直接用 OrderedDict.keys() 顺序)。
        """
        return list(self._buckets.keys())

    def _evict_if_needed(self) -> None:
        while len(self._buckets) > self._total_groups_cap:
            self._buckets.popitem(last=False)
