"""把 SKILL.md 复制到 ~/.hermes/skills/nonebot-bridge/。

使用:
    uv run hermes-install-skill
    或
    python -m hermes_install_skill

此模块是独立入口点,故意不从 nonebot_plugin_hermes 导入任何内容,
以避免在 NoneBot 未初始化时(控制台工具场景)触发插件初始化。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Install nonebot-bridge skill into ~/.hermes/skills/")
    parser.add_argument(
        "--dest",
        default=str(Path.home() / ".hermes" / "skills" / "nonebot-bridge"),
        help="Target directory (default: ~/.hermes/skills/nonebot-bridge)",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite if exists")
    args = parser.parse_args()

    dest = Path(args.dest)
    if dest.exists() and not args.force:
        print(f"[install_skill] target exists: {dest}", file=sys.stderr)
        print("[install_skill] re-run with --force to overwrite", file=sys.stderr)
        return 1

    # Locate SKILL.md relative to this file.
    # In both editable installs (project root) and wheel installs (site-packages),
    # nonebot_plugin_hermes/ sits alongside this file, so the path is always valid.
    src = Path(__file__).parent / "nonebot_plugin_hermes" / "skill" / "SKILL.md"
    if not src.exists():
        print(f"[install_skill] source not found: {src}", file=sys.stderr)
        return 2
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "SKILL.md"
    shutil.copy2(src, target)
    print(f"[install_skill] installed: {target}")
    print("[install_skill] now add to ~/.hermes/config.yaml:")
    print("  mcp_servers:")
    print("    nonebot-bridge:")
    print("      url: http://127.0.0.1:8643/mcp")
    print('      headers: { Authorization: "Bearer <HERMES_API_KEY>" }')
    return 0


if __name__ == "__main__":
    sys.exit(main())
