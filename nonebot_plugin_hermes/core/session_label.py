"""
Session label layer — encode tags/priority/note into Hermes PATCH title prefix.

Why this exists
---------------
Hermes Agent gateway 的 PATCH /api/sessions/{id} 只接受 {title, end_reason}
(没有原生 label 字段)。我们把 label/priority/note 打成「控制字符 + JSON」前缀
塞进 title:

    \x1e{"l":["netops","urgent"],"p":2,"n":"先看 1.1.1"}\x1f<real title>

\x1e (RS, Record Separator) 和 \x1f (US, Unit Separator) 是 ASCII 控制字符,
普通聊天文本里几乎不会出现 —— 我们的 use case 下不会撞前缀。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple


# --- 常量 ---

# ASCII RS / US 是 C0 控制字符, 绝大多数聊天文本不会带,
# 选它们做 prefix 分隔符避免和真实内容冲突
_PREFIX_START = "\x1e"
_PREFIX_END = "\x1f"

# 容量上限:防 gateway 端拒绝、payload 膨胀、key collision
_MAX_LABELS_PER_SESSION = 32
_MAX_LABEL_LEN = 64
_MAX_NOTE_LEN = 280
_MAX_TITLE_LEN = 200  # 留余量在 gateway 的 MAX_SESSION_HEADER_LEN 之下

# 检测前缀: 以 \x1e 开头, 后面是 lazy match 的 JSON, 再到 \x1f
# 故意不用 * 而是 {.*?} 避免贪婪吞掉后面 \x1f
_PREFIX_RE = re.compile(r"^\x1e(\{.*?\})\x1f", re.DOTALL)


@dataclass
class Annotations:
    """一组挂在一个 session 上的标注 (label/priority/note)。

    形态故意保持极简 —— 只有 label 列表、0-3 优先级、单行 note。
    任意升级都意味着改 gateway 协议, 本层不允许放任意 KV。
    """

    labels: List[str] = field(default_factory=list)
    priority: int = 0  # 0=unset, 1=low, 2=med, 3=high
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """打包成短 key 的 dict, 节省 prefix 体积 (短键名压 1/3 字节)。"""
        d: Dict[str, Any] = {"l": list(self.labels), "p": int(self.priority)}
        if self.note:
            d["n"] = self.note
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Annotations":
        """从 dict 还原 —— 所有字段都做防御性校验, 任意坏值都退化成空。

        这是关键: gateway 上 title 可能被任意一方写入, decode 拿到坏 JSON
        时必须不抛, 否则会把整个 chat 路径炸掉。
        """
        if not isinstance(d, dict):
            return cls()
        labels = d.get("l") or []
        if not isinstance(labels, list):
            labels = []
        # 只接受 str/int, 强转 str 后截断 —— 防奇怪的 None / dict 注入
        labels = [str(x) for x in labels if isinstance(x, (str, int))][:_MAX_LABELS_PER_SESSION]
        labels = [x[:_MAX_LABEL_LEN] for x in labels]
        try:
            priority = int(d.get("p", 0))
        except (TypeError, ValueError):
            priority = 0
        # 钳到 [0, 3] —— 网关协议没有定义越界值, UI 也只会画 4 档
        priority = max(0, min(3, priority))
        note = d.get("n")
        if note is not None:
            note = str(note)[:_MAX_NOTE_LEN]
        return cls(labels=labels, priority=priority, note=note)


def encode_annotations(
    *,
    real_title: str,
    annotations: Annotations,
) -> str:
    """把 annotations 打包进 title 字符串, 返回可直接 PATCH 的新 title。

    - annotations 是空 (没 label / priority=0 / 没 note) → 返回 real_title 原样
      (避免无意义 prefix 污染老 title 显示)
    - 输入校验: title 必须 str、不能超长, 否则抛 ValueError (由调用方决定
      是否回退)
    """
    if not isinstance(real_title, str):
        raise ValueError("real_title must be a string")
    if len(real_title) > _MAX_TITLE_LEN:
        raise ValueError(f"real_title too long ({len(real_title)} > {_MAX_TITLE_LEN})")

    # 空 annotation → 保留原 title (零行为变化, 老 UI 看不到 prefix 噪音)
    if not annotations.labels and annotations.priority == 0 and not annotations.note:
        return real_title

    payload = json.dumps(annotations.to_dict(), ensure_ascii=False, separators=(",", ":"))
    prefix = f"{_PREFIX_START}{payload}{_PREFIX_END}"
    return f"{prefix}{real_title}"


def decode_annotations(title: Optional[str]) -> Tuple[Annotations, str]:
    """encode 的逆操作。返回 (annotations, real_title)。

    - 没 prefix → (空 Annotations, 原 title)
    - prefix 坏掉 (JSON 不合法 / 非 dict / 空) → 软失败: 返回 (空 Annotations, 原 title)
      —— 绝不让坏 prefix 把 chat 路径炸掉 (典型场景: 用户粘贴了一段带
      \x1e 的文本当 title, 老客户端原样存进 gateway)
    """
    if not title or not isinstance(title, str):
        return Annotations(), title or ""

    m = _PREFIX_RE.match(title)
    if not m:
        return Annotations(), title

    raw_json = m.group(1)
    real_title = title[m.end():]
    try:
        parsed = json.loads(raw_json)
    except (json.JSONDecodeError, ValueError):
        # JSON 不合法 → 软失败, 原样返回 title 当 real_title
        return Annotations(), title
    if not isinstance(parsed, dict):
        return Annotations(), title
    return Annotations.from_dict(parsed), real_title


def has_annotations(title: Optional[str]) -> bool:
    """便宜的前缀存在性检查 (O(1), 不解析 JSON)。"""
    return bool(title) and title.startswith(_PREFIX_START)


class SessionLabelIndex:
    """进程内内存索引: session_id → Annotations, 反向 label → set[session_id]。

    - 不写盘 —— 重启丢; gateway 是 source of truth, 丢可以 /hermes-label rebuild
    - RLock 保护所有读写, 线程安全; 但 lock 粒度很小, 频繁 chat 路径不会撞
    """

    def __init__(self) -> None:
        self._by_session: Dict[str, Annotations] = {}
        self._by_label: Dict[str, set] = {}  # label → set of session_id
        self._lock = RLock()

    def set(self, session_id: str, ann: Annotations) -> None:
        """写入一个 session 的 annotations; 旧 label 自动从反向索引移除。"""
        with self._lock:
            old = self._by_session.get(session_id)
            if old is not None:
                # 旧 label 全撤掉 (不管新旧是否一致, 一刀切简单可靠)
                for lbl in old.labels:
                    bucket = self._by_label.get(lbl)
                    if bucket is not None:
                        bucket.discard(session_id)
            self._by_session[session_id] = ann
            for lbl in ann.labels:
                self._by_label.setdefault(lbl, set()).add(session_id)

    def get(self, session_id: str) -> Optional[Annotations]:
        """读单个 session 的 annotations; 没命中返回 None。"""
        with self._lock:
            return self._by_session.get(session_id)

    def find_by_label(self, label: str) -> List[str]:
        """反查: 拿一个 label, 返回所有带它的 session_id 列表 (sorted 方便测试和展示)。"""
        with self._lock:
            return sorted(self._by_label.get(label, set()))

    def list_all(self) -> List[Tuple[str, Annotations]]:
        """dump 全部 (admin / debug 用), 返回 [(session_id, ann), ...]"""
        with self._lock:
            return list(self._by_session.items())

    def clear(self) -> None:
        """清空 —— 仅 /hermes-label rebuild 用。"""
        with self._lock:
            self._by_session.clear()
            self._by_label.clear()


# 模块级单例 —— 和 gsskk 现有风格一致 (session_manager、hermes_client 都是 module-level)
label_index = SessionLabelIndex()
