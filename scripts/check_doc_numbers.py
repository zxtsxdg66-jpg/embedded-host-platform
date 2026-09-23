"""核对文档里的规模数字与仓库实际状态是否一致。

测试数、源文件数这类数字会随每次改动一起过期，而过期是无声的：没有任何检查会失败，
只有读文档的人被误导。本脚本从仓库现场数出实际值，再与文档里写的数逐个比对：

- 测试总数：README 与 docs/verification.md 里的"N 项"
- 源文件数：README 里 mypy 的"N 个源文件"
- 各测试目录的用例数：docs/verification.md 的分目录表

用法::

    python scripts/check_doc_numbers.py            # 只报告
    python scripts/check_doc_numbers.py --list     # 顺带列出实测值

退出码 1 表示至少有一处不一致。只报告位置，不自动改写。
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
VERIFICATION = ROOT / "docs" / "verification.md"


def collected_tests() -> Counter[str]:
    """Test counts per top-level tests/ directory, from pytest's own collection."""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    ).stdout
    counts: Counter[str] = Counter()
    for line in out.splitlines():
        match = re.match(r"tests/([^/]+)/.*: (\d+)$", line.replace("\\", "/"))
        if match:
            counts[match.group(1)] += int(match.group(2))
    return counts


def source_files() -> int:
    files = (ROOT / "src").rglob("*.py")
    return sum(1 for p in files if "__pycache__" not in p.parts)


def table_counts(text: str) -> dict[str, int]:
    """Per-directory rows of the test table.

    Handles ``| `protocol/` | 28 |`` and ``| `llm/` / `storage/` | 19 / 67 |``.
    """
    found: dict[str, int] = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        names = re.findall(r"`([a-z_]+)/`", cells[0])
        numbers = re.findall(r"\d+", cells[1])
        only_numbers = cells[1].replace("/", "").replace(" ", "").isdigit()
        if names and len(names) == len(numbers) and only_numbers:
            found.update({name: int(n) for name, n in zip(names, numbers, strict=True)})
    return found


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--list", action="store_true", help="also print measured values"
    )
    args = parser.parse_args()

    per_dir = collected_tests()
    total = sum(per_dir.values())
    sources = source_files()
    problems: list[str] = []

    for doc in (README, VERIFICATION):
        rel = doc.relative_to(ROOT).as_posix()
        text = doc.read_text(encoding="utf-8")
        for number in re.findall(r"(\d{3,5}) 项", text):
            if int(number) != total:
                problems.append(f"{rel}: 写的是 {number} 项，实际 {total} 项")
        for number in re.findall(r"(\d{2,4}) 个源文件", text):
            if int(number) != sources:
                problems.append(f"{rel}: 写的是 {number} 个源文件，实际 {sources} 个")

    table = table_counts(VERIFICATION.read_text(encoding="utf-8"))
    for name, stated in sorted(table.items()):
        if per_dir.get(name) != stated:
            problems.append(
                f"docs/verification.md 分目录表: {name}/ 写的是 {stated}，"
                f"实际 {per_dir.get(name, 0)}"
            )
    for name in sorted(set(per_dir) - set(table)):
        problems.append(
            f"docs/verification.md 分目录表缺少 {name}/（{per_dir[name]} 项）"
        )

    if args.list:
        print(f"测试总数 {total}，src 源文件 {sources}")
        for name, count in sorted(per_dir.items()):
            print(f"  tests/{name}/  {count}")
        print()

    if problems:
        print("不一致：")
        for line in problems:
            print("  " + line)
        return 1
    print("文档里的规模数字与仓库一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
