"""核对文档里那些**机器能核对的事实**与仓库实际状态是否一致。

存在的理由很实际：测试数、源文件数这类数字散落在十几份文档里，
每次功能推进都会让它们一起过期，而过期的方式是无声的——没有任何检查会失败，
只有下一个读文档的人被误导。2026-09-09 的文档审计一次就查出四份文档
分别停留在 513 / 761 / 818 / 82 这些早已作废的数字上。

同一次审计还暴露了另一种同类问题：`Skill_Audit_Report.md` 第 6 节自称
"当前状态"，列的却是 2026-08-11 的 10 active / 4 archived，而实际目录里
已经是 12 / 5。**一份自称"当前"的清单，必须能被机器和真实目录对上**，
否则它比没有更糟——读的人会当真。因此本脚本查两件事：

1. 文档里残留的历史数字
2. `Skill_Audit_Report.md` 第 6 节的 skill 清单与 `.claude/` 两个目录是否一致

用法::

    python scripts/check_doc_numbers.py            # 只报告
    python scripts/check_doc_numbers.py --list     # 顺带列出当前实测值

退出码 1 表示至少有一处不一致。**它检查的是"文档里出现的数字是不是当前值"，
不是"文档写全了没有"** —— 后者需要人读，这里只挡住机器能挡的那一半。

刻意不做自动改写：某些出现是历史记录（"测试基线 513 → 761"这类推进日志里的
句子就该保持原样），机器分不清哪一处该改。所以只报告位置，由人决定。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 这些文件按性质就应当保留历史数字，不参与检查
EXEMPT = (
    "docs/01_Project/项目推进日志.md",
    # status/ 整卷都是按日期写死的过程记录（"当时 627 个测试全绿"这类），
    # 它们记录的是事件而非现状，本就该保持原样。2026-09-09 由单独豁免
    # 早期归档.md 扩为整个目录。
    "docs/05_Test/status/",
    "docs/07_Thesis/归档/",
    "docs/08_YINGJIAN/",
    "docs/07_Thesis/实验数据/",
)

# 已知的历史值：出现即可疑。
#
# 这张表只兜底那些**小于 SUBCOUNT_CEILING** 的历史总数（早期用例还不多时留下的）。
# 大于它的一律由 scan() 自动判定，不必再往这里补——2026-09-09 一天之内用例数
# 走了 900 → 904 → 907 → 911，每次都要手工往黑名单里加一条，而漏加的后果是
# 检查静默通过，正是这个脚本存在的理由本身。
STALE_TESTS = ("454", "462", "471", "474")
STALE_FILES = ("68", "74", "82", "85", "87")

SUBCOUNT_CEILING = 400
"""区分"过期的总数"与"合法的分项数"的门槛。

处在总数位置（"N 项"／"N 个用例"／"N passed"）的数字，如果既不等于当前实测值、
又不小于本门槛，就判定为过期总数。取 400 的依据是两侧都留足余量：分层用例数
最大的一项是服务层 229，而全项目总数已过 900。分项数字要涨到 400 才会误报，
那时这个门槛该跟着调——但那也意味着项目规模翻了一倍。

需要写一个大于门槛、又确实不是当前总数的数字时（例如引用某次历史基线），
按下面 scan() 的约定给它带上"当时／曾／原为／时为"或"→"。
"""


def measure() -> dict[str, int]:
    """实测当前的三个数字。"""
    # 不加 -q：简洁模式下"N passed"那一行会被进度条覆盖，抓不到。
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(ROOT / "tests"), "--no-header"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    # stdout 可能为 None（子进程异常退出），也可能没有 "N passed"（有用例失败）。
    # 这个脚本常在测试刚挂掉时被跑到，那正是最需要它把话说清楚的时刻，
    # 所以两种情况都退回 -1 而不是抛栈。
    match = re.search(r"(\d+) passed", proc.stdout or "")
    tests = int(match.group(1)) if match else -1

    sources = [
        f
        for f in (ROOT / "src").rglob("*.py")
        if "__pycache__" not in str(f)
    ]

    chapters = sorted((ROOT / "docs" / "07_Thesis").glob("第*章*.md"))
    words = 0
    for chapter in chapters:
        text = chapter.read_text(encoding="utf-8")
        body = re.sub(r"^\s*\|.*$", "", text, flags=re.M)  # 表格不计入正文字数
        words += len(re.findall(r"[一-鿿]", body))

    # 网关用例数：文档里"上位机部分 N 个用例（不含网关）"是一个同样合法的
    # 总数，与全项目总数只差网关那一档。不把它算进来，每次都会误报一次。
    gateway = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            str(ROOT / "tests" / "gateway"), "-q", "--collect-only",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    counted = sum(
        int(m.group(1)) for m in re.finditer(r"\.py: (\d+)", gateway.stdout or "")
    )

    return {
        "tests": tests,
        "tests_no_gateway": tests - counted if tests > 0 and counted else -1,
        "sources": len(sources),
        "words": words,
    }


def check_skill_lists() -> list[str]:
    """比对 Skill_Audit_Report 第 6 节与 .claude/ 下的实际目录。

    只查第 6 节（自称当前状态的那一节）。第 1~5 节是 2026-08-11 的审计存档，
    里面的清单本就该保持历史原样。
    """
    report = ROOT / "docs" / "04_Development" / "Skill_Audit_Report.md"
    if not report.is_file():
        return [f"找不到 {report.name}"]

    text = report.read_text(encoding="utf-8")
    marker = "## 6. 当前状态"
    if marker not in text:
        return [f"{report.name} 缺少『{marker}』一节，无法核对 skill 清单"]
    section = text[text.index(marker):]

    problems: list[str] = []
    installed: set[str] = set()
    for label, folder in (("active", "skills"), ("archive", "archive_skills")):
        directory = ROOT / ".claude" / folder
        if not directory.is_dir():
            continue
        actual_names = {d.name for d in directory.iterdir() if d.is_dir()}
        installed |= actual_names
        missing = sorted(n for n in actual_names if f"`{n}`" not in section)
        if missing:
            problems.append(
                f"{report.name} 第 6 节的 {label} 清单未提到："
                + "、".join(missing)
            )

    # 反方向：清单里写了、目录里却没有。只看表格行首的反引号名，避免把
    # 正文里顺带提到的名字（"以 xxx 为准"）也当成清单项。
    listed = set(re.findall(r"^\| `([a-z0-9-]+)`", section, re.M))
    listed |= set(re.findall(r"^\| `([a-z0-9-]+)` `", section, re.M))
    for row in re.findall(r"^\| (`[a-z0-9-]+`(?: `[a-z0-9-]+`)+)", section, re.M):
        listed |= set(re.findall(r"`([a-z0-9-]+)`", row))
    vanished = sorted(listed - installed)
    if vanished:
        problems.append(
            f"{report.name} 第 6 节列出了但 .claude/ 下已不存在："
            + "、".join(vanished)
        )
    return problems


def scan(actual: dict[str, int]) -> list[tuple[Path, int, str]]:
    """找出仍然写着历史数字的位置。"""
    findings: list[tuple[Path, int, str]] = []
    # 先框出"处在总数位置"的所有数字，再逐个判断，而不是拿一张固定清单去撞。
    test_pattern = re.compile(
        r"\b(\d{3,5})\b\s*(?=项|个(?:测试|用例)|passed|条用例)"
    )
    file_pattern = re.compile(r"\b(" + "|".join(STALE_FILES) + r")\s*个源文件")

    for path in sorted(ROOT.glob("**/*.md")):
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(x) or x in rel for x in EXEMPT):
            continue
        if any(part in rel for part in (".venv", "node_modules", ".claude", "build")):
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            # 明确写成过去式的句子不算过期——"当时的 593 个用例全绿"记录的是
            # 一个事件，不是一个现状。这条豁免靠措辞识别，因此写文档时请把
            # 历史数字带上"当时/曾/原为/时为"这类限定词。
            if any(word in line for word in ("当时", "曾", "原为", "时为", "→")):
                continue
            for hit in test_pattern.finditer(line):
                value = int(hit.group(1))
                if value in (actual["tests"], actual["tests_no_gateway"]):
                    continue
                # 小于门槛的当作合法分项（网关 25、服务 229 之类），
                # 只有明确列入 STALE_TESTS 的才报。
                if value < SUBCOUNT_CEILING and hit.group(1) not in STALE_TESTS:
                    continue
                findings.append((path, number, f"测试数 {value}"))
            hit = file_pattern.search(line)
            if hit:
                findings.append((path, number, f"源文件数 {hit.group(1)}"))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="核对文档中的项目规模数字")
    parser.add_argument("--list", action="store_true", help="列出当前实测值")
    args = parser.parse_args(argv)

    actual = measure()
    if args.list:
        print(f"当前实测：测试 {actual['tests']} 项 / "
              f"src {actual['sources']} 个源文件 / 论文正文 {actual['words']} 汉字")

    findings = scan(actual)
    skill_problems = check_skill_lists()

    if not findings and not skill_problems:
        print("[OK] 文档数字与 skill 清单均与实际一致")
        return 0

    if findings:
        print(f"[NG] {len(findings)} 处文档数字疑似过期"
              f"（当前：测试 {actual['tests']} / 源文件 {actual['sources']}）：")
        for path, line, what in findings:
            print(f"  {path.relative_to(ROOT).as_posix()}:{line}  {what}")
        print("历史记录性质的文件已豁免；若某处确属历史叙述，把它加进 EXEMPT。")

    if skill_problems:
        print("[NG] skill 清单与 .claude/ 实际目录不一致：")
        for problem in skill_problems:
            print(f"  {problem}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
