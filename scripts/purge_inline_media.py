#!/usr/bin/env python3
"""把消息库里内联的 base64 data URL 原地换成 [图片] 占位。

用途:0.2.x 之前 reactive 路径把 bot 回复原文写进 messages.content,api_server 内联的
图片(data:image/…;base64,…)因此整段落库 —— 单条能到 1MB 量级。写入端已经改成只存
清洗后的文本 + [图片],渲染端也会兜底截断,所以旧行**不再影响 prompt**;这个脚本只是
把已经躺在库里的字节清出去,省磁盘和每 turn 的无谓读放大。

不删行:那会连带丢掉同一条消息里的正常文本,以及 bot 自己那条历史(decision_protocol
的「自我归因校验」要靠它定位自己说过什么)。只替换 payload,长度之外的语义不变。

默认 dry-run,只报告不改动;确认后加 --apply。

    python3 scripts/purge_inline_media.py --db /path/to/messages.db
    python3 scripts/purge_inline_media.py --db /path/to/messages.db --apply

故意不 import nonebot_plugin_hermes:`-m` / 直接 import 都会连带执行包的 __init__,
里面的 require() 在没有 NoneBot 进程时直接抛错(与 hermes_install_skill.py 同因)。
因此这里自带一份与 prompt_builder 同义的正则(见下方常量),改一处记得同步。
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

# 与 core/prompt_builder 的 _MD_DATA_IMAGE_IN_HISTORY_RE / _BARE_DATA_URL_IN_HISTORY_RE
# 保持同义:先连 markdown 壳一起换,再兜裸 data URL。
_MD_DATA_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*data:[\w.+-]+/[\w.+-]+;base64,[A-Za-z0-9+/=\s]*\)?")
_BARE_DATA_URL_RE = re.compile(r"data:[\w.+-]+/[\w.+-]+;base64,[A-Za-z0-9+/=\s]+")
_PLACEHOLDER = "[图片]"


def _repl(m: re.Match[str]) -> str:
    """换成 [图片],但把匹配尾部的空白还回去 —— 字符类含 \\s(base64 可能折行),
    否则会顺手吃掉 payload 后面那个空格。"""
    matched = m.group(0)
    return _PLACEHOLDER + matched[len(matched.rstrip()) :]


def _strip_inline_media(content: str) -> str:
    return _BARE_DATA_URL_RE.sub(_repl, _MD_DATA_IMAGE_RE.sub(_repl, content))


# 只有内联 payload 才会把单条撑到这个量级;低于此值的长消息是正常的长回复,不碰。
_REPORT_THRESHOLD = 2000


def _default_db() -> Path | None:
    env = os.environ.get("HERMES_STORAGE_DB_PATH")
    if env:
        return Path(env)
    guess = Path.home() / ".local" / "share" / "nonebot2" / "nonebot_plugin_hermes" / "messages.db"
    return guess if guess.exists() else None


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024.0
    return f"{n}B"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--db", default=None, help="messages.db 路径(默认取 HERMES_STORAGE_DB_PATH / localstore 常规位置)"
    )
    parser.add_argument("--apply", action="store_true", help="真的写回;缺省只报告")
    parser.add_argument("--vacuum", action="store_true", help="写回后跑 VACUUM 收缩文件(需要额外磁盘,期间锁库)")
    parser.add_argument("--limit-preview", type=int, default=10, help="报告里最多列几条(默认 10)")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else _default_db()
    if db_path is None:
        print("[purge] 找不到 messages.db,请用 --db 指定路径", file=sys.stderr)
        return 2
    if not db_path.exists():
        print(f"[purge] 文件不存在: {db_path}", file=sys.stderr)
        return 2

    # timeout:插件是 WAL 模式常驻连接,单写者,拿不到锁时等一会而不是立刻炸。
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        total_rows, total_bytes = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(length(content)), 0) FROM messages"
        ).fetchone()
        print(f"[purge] {db_path}")
        print(f"[purge] 全库 {total_rows} 行,content 合计 {_human(total_bytes)}")

        # 命中判定用 SQL LIKE 粗筛(走不了正则),精确替换在 Python 侧做
        rows = conn.execute(
            "SELECT id, adapter, group_id, is_bot, length(content) AS len, content "
            "FROM messages WHERE content LIKE '%;base64,%' ORDER BY len DESC"
        ).fetchall()
        if not rows:
            print("[purge] 没有内联 base64 的行,无需处理")
            return 0

        updates: list[tuple[str, int]] = []
        saved = 0
        for r in rows:
            cleaned = _strip_inline_media(r["content"])
            if cleaned == r["content"]:
                continue
            updates.append((cleaned, r["id"]))
            saved += r["len"] - len(cleaned)

        by_group: dict[str, list[sqlite3.Row]] = {}
        for r in rows:
            by_group.setdefault(f"{r['adapter']}/{r['group_id']}", []).append(r)
        print(f"[purge] 命中 {len(updates)} 行,可回收 {_human(saved)}")
        for scope, group_rows in sorted(by_group.items(), key=lambda kv: -sum(x["len"] for x in kv[1])):
            print(f"[purge]   {scope}: {len(group_rows)} 行,最大 {_human(max(x['len'] for x in group_rows))}")
        print(f"[purge] 最长的 {min(args.limit_preview, len(rows))} 条:")
        for r in rows[: args.limit_preview]:
            head = r["content"][:60].replace("\n", "\\n")
            print(f"[purge]   id={r['id']} is_bot={r['is_bot']} len={_human(r['len'])} head={head!r}")

        # 顺带报告:剥完仍然超长的行(真的是长文本,不是图),留给人判断
        still_big = [(cleaned, rid) for cleaned, rid in updates if len(cleaned) > _REPORT_THRESHOLD]
        if still_big:
            print(f"[purge] 注意:{len(still_big)} 行剥掉图片后仍 >{_REPORT_THRESHOLD} 字符(是长文本,本脚本不截断)")

        if not args.apply:
            print("[purge] dry-run 结束,未改动。确认后加 --apply")
            return 0

        with conn:  # 单事务,失败整体回滚
            conn.executemany("UPDATE messages SET content = ? WHERE id = ?", updates)
        print(f"[purge] 已写回 {len(updates)} 行")

        if args.vacuum:
            print("[purge] VACUUM 中(锁库,视库大小可能要几十秒)…")
            conn.execute("VACUUM")
            print("[purge] VACUUM 完成")
        else:
            print("[purge] 未 VACUUM:文件大小不会立刻变小,空间会被后续写入复用。要立刻收缩加 --vacuum")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
