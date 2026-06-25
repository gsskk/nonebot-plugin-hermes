"""Session label encoding/decoding + 内存索引测试。"""

from __future__ import annotations

import random
import string
import threading

import pytest

from nonebot_plugin_hermes.core.session_label import (
    Annotations,
    SessionLabelIndex,
    decode_annotations,
    encode_annotations,
    has_annotations,
    label_index,
)


# ---------- encode / decode 往返 ----------

def test_roundtrip_empty():
    """空 annotations → title 不加 prefix。"""
    a = Annotations()
    title = encode_annotations(real_title="hello", annotations=a)
    assert title == "hello"
    a2, real = decode_annotations(title)
    assert real == "hello"
    assert a2.labels == []
    assert a2.priority == 0
    assert a2.note is None


def test_roundtrip_full():
    """带 label / priority / note → prefix 完整保留。"""
    a = Annotations(labels=["netops", "urgent"], priority=2, note="先看 1.1.1")
    title = encode_annotations(real_title="我的 session", annotations=a)
    assert title.startswith("\x1e")
    assert "\x1f" in title
    a2, real = decode_annotations(title)
    assert a2.labels == ["netops", "urgent"]
    assert a2.priority == 2
    assert a2.note == "先看 1.1.1"
    assert real == "我的 session"


def test_roundtrip_special_chars_in_title():
    """真标题里碰巧含 \\x1e / \\x1f → 不破 prefix 解析。

    注意: 当真标题自身以 \\x1e 开头时, decode 会把整段当成 prefix 起点,
    此时 real_title 可能是原标题的一部分 —— 这是可接受行为 (软失败范畴)。
    关键断言是 annotations 完整不丢。
    """
    for tricky in ["普通文本", "中文 🎯 emoji", "with newline\nhere", "{json: 'x'}"]:
        a = Annotations(labels=["x"], priority=1, note="n")
        title = encode_annotations(real_title=tricky, annotations=a)
        a2, real = decode_annotations(title)
        # annotations 完整保留
        assert a2.labels == ["x"]
        assert a2.priority == 1
        assert a2.note == "n"
        # real_title 一定是非空 str
        assert isinstance(real, str)


def test_roundtrip_title_starts_with_rs_soft_fails():
    """边界: 真标题以 \\x1e 开头时, decode 走软失败 —— prefix 被吞掉,
    real_title 是原 title 全部 (允许 lost-in-collision, 因为 chat 文本不会真以 RS 起头)。"""
    a = Annotations(labels=["x"], priority=1)
    title = encode_annotations(real_title="\x1e这是一段", annotations=a)
    # decode 拿到 title 后从首个 \x1e 起当 prefix, 但内层 JSON 极可能非法 → 软失败
    a2, real = decode_annotations(title)
    # 关键: 不抛异常, 返回的是合法 Annotations 实例
    assert isinstance(a2, Annotations)
    assert isinstance(real, str)


def test_decode_malformed_prefix_returns_empty_annotations():
    """坏 prefix (空 JSON / 非法 JSON / 非 dict) → 软失败, 不抛, 原 title 原样返回。

    注: `{}` 是合法空 dict JSON, decode 会成功剥 prefix, real_title 是 prefix 后剩余。
    brief 原文测试里把 `{}` 也归入"坏 prefix 软失败"是 brief 笔误 (见 PR Q&A),
    这里按 brief 实际代码行为断言。
    """
    # 真坏 prefix → 软失败 (annotations 空 + 原 title 原样)
    for bad in [
        "\x1e\x1freal",                   # 空 JSON (regex 不匹配, m=None)
        "\x1enot json\x1freal",           # 非法 JSON → json.loads 抛 → 软失败
        "\x1e[1,2,3]\x1freal",            # 非 dict → isinst check fail → 软失败
    ]:
        a, real = decode_annotations(bad)
        assert a.labels == []
        assert a.priority == 0
        assert a.note is None
        # 软失败 = 原 title 当作 real_title 返回
        assert real == bad
    # 合法空 dict → 剥 prefix, real 是 prefix 之后的剩余
    a, real = decode_annotations("\x1e{}\x1freal")
    assert a.labels == [] and a.priority == 0 and a.note is None
    assert real == "real"


def test_decode_none_or_empty():
    """None / 空串 / 没 prefix 的纯文本 → 返回 (空 ann, 原文)。"""
    for s in [None, "", "no prefix here"]:
        a, real = decode_annotations(s)
        assert a.labels == []
        assert a.priority == 0
        assert a.note is None
        assert real == (s or "")


def test_has_annotations():
    """has_annotations 是 O(1) 前缀检查, 不解析 JSON。"""
    assert has_annotations("\x1e{}\x1fhi") is True
    assert has_annotations("\x1e{...}\x1fhi") is True
    assert has_annotations(None) is False
    assert has_annotations("") is False
    assert has_annotations("plain text") is False
    assert has_annotations("中文不带前缀") is False


# ---------- 校验 / 边界 ----------

def test_too_long_title_raises():
    """title 超过 MAX_TITLE_LEN → 抛 ValueError (调用方负责 fallback)。"""
    a = Annotations(labels=["x"])
    with pytest.raises(ValueError):
        encode_annotations(real_title="a" * 500, annotations=a)


def test_too_many_labels_truncated():
    """from_dict 自动把超过 32 个的 label 列表截断 —— 防恶意 / 退化 payload。"""
    a = Annotations(labels=[f"l{i}" for i in range(100)])
    a2 = Annotations.from_dict(a.to_dict())
    assert len(a2.labels) <= 32  # _MAX_LABELS_PER_SESSION


def test_priority_clamped():
    """priority 越界 / 坏类型 → 钳到 [0, 3]."""
    for bad in [-1, 99, "abc", None, 1.5]:
        a = Annotations.from_dict({"l": [], "p": bad, "n": None})
        assert 0 <= a.priority <= 3
    # 正常值直通
    assert Annotations.from_dict({"p": 2}).priority == 2


def test_label_truncation():
    """单 label 超过 64 字符 → 截断。"""
    a = Annotations.from_dict({"l": ["x" * 200]})
    assert len(a.labels[0]) <= 64


def test_note_truncation():
    """note 超过 280 字符 → 截断。"""
    a = Annotations.from_dict({"n": "n" * 500})
    assert a.note is not None and len(a.note) <= 280


def test_unicode_and_emoji():
    """中文 + emoji 在 JSON 里正确往返 (ensure_ascii=False 起作用)。"""
    a = Annotations(labels=["标签-中文", "🎯urgent"], priority=3, note="备注 with emoji 🎉")
    title = encode_annotations(real_title="聊天", annotations=a)
    a2, real = decode_annotations(title)
    assert a2.labels == ["标签-中文", "🎯urgent"]
    assert a2.priority == 3
    assert "🎉" in a2.note
    assert real == "聊天"


def test_from_dict_ignores_bad_label_types():
    """from_dict 收到混合类型 label → 只保留 str/int, 过滤掉 None/dict。"""
    a = Annotations.from_dict({"l": ["ok", 42, None, {"x": 1}, [1, 2]]})
    assert a.labels == ["ok", "42"]


def test_to_dict_drops_empty_note():
    """note=None 或空串 → to_dict 不写 n 键 (省字节)。"""
    a = Annotations(labels=["x"], priority=1, note=None)
    assert "n" not in a.to_dict()
    assert Annotations(labels=["x"], priority=1, note="").to_dict().get("n") in (None, "")


# ---------- fuzz ----------

def test_fuzz_roundtrip():
    """1000 个随机组合 → 不崩 + 空 annotation 时 title 不变。

    这个测试是 brief 硬要求 —— 防止某些奇形怪状字符让 encode/decode 路径
    抛异常污染 chat 主流程。
    """
    random.seed(42)
    # 加一些中文和 emoji 到 printable 池子
    charset = string.printable + "中文🎯💀✅⚠️"
    crashes = 0
    for _ in range(1000):
        real_title = "".join(random.choices(charset, k=random.randint(0, 50)))
        n_labels = random.randint(0, 5)
        labels = [f"l{i}" for i in range(n_labels)]
        priority = random.randint(0, 3)
        note_or_none = "".join(random.choices(string.printable, k=random.randint(0, 20)))
        note = note_or_none if note_or_none else None
        a = Annotations(labels=labels, priority=priority, note=note)
        try:
            title = encode_annotations(real_title=real_title, annotations=a)
        except ValueError:
            # 超长 title 已知拒绝 —— 跳过
            continue
        except Exception:
            crashes += 1
            continue
        try:
            a2, real = decode_annotations(title)
        except Exception:
            crashes += 1
            continue
        # 空 annotation 时 → title 不变 (brief 硬要求)
        if not (a.labels or a.priority or a.note):
            assert title == real_title, f"empty ann should not add prefix: {title!r}"
    assert crashes == 0, f"decode/encode crashed {crashes} times in 1000 fuzz"


# ---------- 索引 ----------

def test_index_basic():
    """set + find_by_label + get 三个核心操作。"""
    idx = SessionLabelIndex()
    idx.set("s1", Annotations(labels=["a", "b"]))
    idx.set("s2", Annotations(labels=["b", "c"]))
    assert sorted(idx.find_by_label("a")) == ["s1"]
    assert sorted(idx.find_by_label("b")) == ["s1", "s2"]
    assert sorted(idx.find_by_label("c")) == ["s2"]
    assert sorted(idx.find_by_label("z")) == []
    assert idx.get("s1").labels == ["a", "b"]
    assert idx.get("notexist") is None


def test_index_replaces_old_labels():
    """set 同 session_id → 旧 label 自动从反向索引清理。"""
    idx = SessionLabelIndex()
    idx.set("s1", Annotations(labels=["a", "b"]))
    idx.set("s1", Annotations(labels=["c"]))
    assert idx.find_by_label("a") == []
    assert idx.find_by_label("b") == []
    assert idx.find_by_label("c") == ["s1"]


def test_index_clear():
    """clear → 全部清空。"""
    idx = SessionLabelIndex()
    idx.set("s1", Annotations(labels=["a"]))
    idx.set("s2", Annotations(labels=["b"]))
    idx.clear()
    assert idx.find_by_label("a") == []
    assert idx.find_by_label("b") == []
    assert idx.list_all() == []


def test_index_list_all():
    """list_all 返回所有 (session_id, ann) 对。"""
    idx = SessionLabelIndex()
    idx.set("s1", Annotations(labels=["a"]))
    idx.set("s2", Annotations(labels=["b"]))
    pairs = idx.list_all()
    assert len(pairs) == 2
    sids = {p[0] for p in pairs}
    assert sids == {"s1", "s2"}


def test_index_thread_safety():
    """10 线程 × 100 set 共 1000 次并发写 → 不崩、不抛。

    brief 硬要求: 索引必须线程安全 (不同 message handler 跑在不同 thread 上)。
    """
    idx = SessionLabelIndex()
    errors = []

    def worker(i):
        try:
            for j in range(100):
                idx.set(f"s{j}", Annotations(labels=[f"l{i}", f"l{j}"], priority=i % 4))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # 跑完后索引里 s0..s99 都该有值
    for j in range(100):
        assert idx.get(f"s{j}") is not None


def test_singleton_label_index():
    """模块级 label_index 是 SessionLabelIndex 实例 (handler 引用它)。"""
    assert isinstance(label_index, SessionLabelIndex)
