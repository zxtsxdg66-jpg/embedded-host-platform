"""Rehearse the whole demonstration flow headlessly, against the real model.

Purpose
-------
Run this before a demonstration to find out **what the local model is going
to do today**. It composes exactly what ``run_gui.py`` composes -- the same
simulator runtime, the same ``attach_language_model()``, the same
``poll_once()`` -- and then types a fixed script of questions and
instructions through it. The only thing missing is the window.

Why it exists at all
--------------------
It was written as a throwaway check and immediately earned a permanent
place: the first run exposed two rule gaps that the 800-odd unit tests did
not, because unit tests cover the phrasings someone thought of, and a
rehearsal covers the ones they did not:

- "这一阵子最吵到多少" was answered with the *current* reading, because the
  rules only knew 最高/最大/峰值 as superlatives.
- "把通风温度阈值调低一点" was answered with the fan's state, because the
  threshold branch demanded a number before it would treat a sentence as an
  instruction.

Both produced perfectly plausible answers, which is exactly what made them
easy to miss. See docs/02_Architecture/Assistant_Design.md section 13.6.

What it reports
---------------
Every utterance's immediate answer, the model's later answer if one
arrives, and the ventilation settings afterwards -- then a stability
summary comparing the rounds. What is compared is how each sentence was
*understood* (its intent kind, and whether an instruction was carried
out), not the words that came back: readings differ between rounds by
design, and comparing wording would report that as instability.

Exit code is 1 only if the same sentence ever **carried out two different
actions**. Everything else -- an instruction understood in one round and
declined in another, an ambiguous question ("站里闷不闷" -- temperature or
humidity?) answered two ways -- is reported without failing, because the
system did nothing wrong in those rounds: it declined, or it answered a
different real reading. That distinction is the point of the tool.
"不稳定" would otherwise read as "可能会乱动"，which is exactly what the
whole design prevents.

Usage::

    python scripts/demo_rehearsal.py                # 2 rounds
    python scripts/demo_rehearsal.py --rounds 3
    python scripts/demo_rehearsal.py --no-llm       # rules and templates only
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from application.runtime import ApplicationRuntime  # noqa: E402
from scripts.automation_wiring import (  # noqa: E402
    attach_language_model,
    make_poll_once,
)
from scripts.run_gui import build_simulator_runtime  # noqa: E402
from service.assistant.control import CONTROL_KINDS  # noqa: E402
from service.assistant.models import Answer  # noqa: E402

QUESTION = "问"
INSTRUCTION = "指令"
OUT_OF_SCOPE = "范围外"

UTTERANCES: tuple[tuple[str, str], ...] = (
    # 开场就少说了通道：系统反问，用户回一个词（2026-09-08 新增）。
    # 放在最前面是必要的——后面任何一句点名通道的提问都会留下记忆，
    # 再问"超标了吗"就会被记忆补上，反问那条路径根本走不到。
    ("超标了吗", QUESTION),
    ("噪声", QUESTION),
    # 规则直接命中的提问
    ("现在温度多少", QUESTION),
    ("噪声超标了吗", QUESTION),
    ("这一阵子最吵到多少", QUESTION),
    ("风扇在转吗", QUESTION),
    # 口语提问：规则落空，交给模型分类
    ("外面冷不冷", QUESTION),
    ("站里闷不闷", QUESTION),
    # 追问：本身没点名通道，靠上一句的通道接上（2026-09-08 新增）
    ("现在噪声多少", QUESTION),
    ("最高呢", QUESTION),
    ("那湿度呢", QUESTION),
    ("超标了吗", QUESTION),
    # 规则直接命中的指令
    ("把风扇打开", INSTRUCTION),
    ("风扇交给自动", INSTRUCTION),
    ("把通风温度阈值调到 28 度", INSTRUCTION),
    # 口语指令：规则落空，交给模型分类
    ("太热了让那个吹风的转起来", INSTRUCTION),
    ("别吹了关上吧", INSTRUCTION),
    # 应当被拒绝的
    ("通风温度阈值调到 300 度", INSTRUCTION),
    ("把通风温度阈值调低一点", INSTRUCTION),
    ("帮我订张票", OUT_OF_SCOPE),
)
"""The script, ordered the way a demonstration would run it.

Deliberately mixes phrasings the rules know with ones they do not, so the
report shows both paths, and keeps the four follow-ups in sequence -- they
only mean anything read in order, which is the point of rehearsing a script
rather than a bag of sentences -- and includes three utterances that *should* be
refused, because a rehearsal that only exercises the happy path would miss
a system that had started saying yes to everything.
"""

DEFAULT_WAIT_SECONDS = 20.0
"""How long to wait for a model answer before moving on.

Matches ``OllamaClient``'s own deadline, so this script never gives up on
a request the application itself would still have been waiting for. That
cost nothing to raise because an instruction is not waited on at all (see
:func:`_expects_model`), and every other utterance stops waiting the
moment its answer lands -- typically 2~4 s.

It was 8 s at first, and a rehearsal run reported "指令类不一致" because
one classification took longer than that. The instruction had been
carried out correctly both times; only this script's patience differed.
A test tool that reports a failure it caused itself is worse than no
tool, hence the alignment with the client's own timeout.
"""

_WARMUP_CYCLES = 40
"""Poll cycles before the script starts, so statistics have samples in them
and "最高值" has something to report."""


def _outcome(answer: Answer) -> str:
    """What is compared between rounds: how the sentence was *understood*.

    Not the rendered text. Readings change from round to round by design,
    and so does whether the fan is currently wanted -- comparing wording
    would report that ordinary variation as instability. The intent kind,
    plus whether an instruction was carried out, is exactly the part that
    should not vary.
    """
    kind = "?" if answer.intent is None else answer.intent.kind.value
    applied = "-" if answer.facts is None else str(answer.facts.applied)
    return f"{answer.source.value}|{kind}|applied={applied}"


def _expects_model(answer: Answer) -> bool:
    """Whether this answer could still be followed by a model result.

    An instruction is carried out by code the moment it is understood and
    is deliberately never reworded, so waiting on it only burns the
    timeout. Everything else either started a rephrasing (the rules
    understood it) or a classification (they did not).
    """
    return answer.intent is None or answer.intent.kind not in CONTROL_KINDS


def _run_round(
    runtime: ApplicationRuntime,
    poll_once: Callable[[], None],
    wait: float,
) -> dict[str, str]:
    """Type the whole script once; return how each utterance was understood."""
    # Each round is a separate conversation. Since the assistant gained a
    # memory of what was last asked, a round that inherited the previous
    # one's topic would not be a repeat of it -- and the stability check
    # below compares rounds.
    runtime.assistant.reset_conversation()
    outcome: dict[str, str] = {}
    for utterance, kind in UTTERANCES:
        answer = runtime.ask(utterance)
        print(f"\n> {utterance}   （{kind}）")
        print(f"  [{answer.source.value}] {answer.text.splitlines()[0][:64]}")
        final = answer

        deadline = time.monotonic() + (wait if _expects_model(answer) else 0.0)
        while time.monotonic() < deadline:
            poll_once()
            later = runtime.poll_assistant()
            if later is not None:
                elapsed = wait - (deadline - time.monotonic())
                print(
                    f"  -> {elapsed:4.1f}s [{later.source.value}] "
                    f"{later.text.splitlines()[0][:64]}"
                )
                final = later
                break
            time.sleep(0.02)

        settings = runtime.get_ventilation_settings()
        print(
            f"    通风设置：温度 {settings.temperature_max:g}℃ / "
            f"湿度 {settings.humidity_max:g}%RH / {settings.mode.name}"
        )
        outcome[utterance] = _outcome(final)
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="演示流程演练（无界面）")
    parser.add_argument("--rounds", type=int, default=2, help="重复轮数（默认 2）")
    parser.add_argument(
        "--wait",
        type=float,
        default=DEFAULT_WAIT_SECONDS,
        help=f"等模型回答的秒数（默认 {DEFAULT_WAIT_SECONDS:g}）",
    )
    parser.add_argument(
        "--no-llm", action="store_true", help="不接模型，只走规则与模板"
    )
    args = parser.parse_args(argv)

    runtime, runner = build_simulator_runtime()
    available, detail = attach_language_model(runtime, enabled=not args.no_llm)
    state = "已接入" if available else "未接入"
    print(f"模型：{state}{' — ' + detail if detail else ''}")

    # The launcher hands ``make_poll_once`` a sink that receives (text,
    # source); this script collects the model's answers itself instead,
    # because it needs the Answer object -- a view only ever needs the two
    # strings. Everything else in the cycle is the launcher's own.
    poll_once = make_poll_once(runtime, runner)
    for _ in range(_WARMUP_CYCLES):
        poll_once()

    seen: dict[str, set[str]] = defaultdict(set)
    for round_no in range(1, args.rounds + 1):
        print(f"\n{'=' * 70}\n第 {round_no} 轮\n{'=' * 70}")
        results = _run_round(runtime, poll_once, args.wait)
        for utterance, outcome in results.items():
            seen[utterance].add(outcome)

    return _report(seen)


def _actions(outcomes: set[str]) -> set[str]:
    """The distinct actions actually carried out among ``outcomes``."""
    return {o.split("|")[1] for o in outcomes if o.endswith("applied=True")}


def _kinds(outcomes: set[str]) -> set[str]:
    """The distinct intent kinds among ``outcomes``."""
    return {o.split("|")[1] for o in outcomes}


def _describe(outcomes: set[str]) -> tuple[str, bool]:
    """Say what kind of instability this is, and whether it is a failure.

    Four cases, in descending order of seriousness. Only the first is a
    defect -- the rest are the system declining or being asked something
    ambiguous, and calling those "failures" would train the reader to
    ignore the report.
    """
    if len(_actions(outcomes)) > 1:
        return "**执行了不同的动作**", True
    if len(_kinds(outcomes)) == 1:
        return "理解一致，只是措辞来源不同（模型改写这一轮没赶上或被拒绝）", False
    if "help" in _kinds(outcomes):
        return "有时听懂、有时只给了帮助文案（是拒绝，不是误执行）", False
    return "回答了不同的问题（都是真实读数，没有副作用）", False


def _report(seen: dict[str, set[str]]) -> int:
    """Print the stability summary; return the process exit code.

    Two kinds of instability, and only one of them is a defect:

    - **两种不同的动作** -- the same sentence turned the fan on once and
      off another time. Nothing observed has ever done this, and if it
      ever does it is the serious case: exit 1.
    - **有时听懂、有时没听懂** -- one round carried the instruction out,
      another showed the help text. The system did nothing wrong; it
      declined. Reported, not failed, because that is the ordinary
      behaviour of a 4B model on colloquial phrasing and the whole design
      is built to make it harmless.

    The distinction is the point of the tool. "不稳定" would otherwise
    read as "可能会乱动"， which is exactly what it is not.
    """
    unstable = [u for u, outcomes in seen.items() if len(outcomes) > 1]
    print(f"\n{'=' * 70}\n稳定性")
    if not unstable:
        print("  全部一致。")
        return 0

    conflicting = False
    for utterance in unstable:
        kind = dict(UTTERANCES)[utterance]
        note, failed = _describe(seen[utterance])
        conflicting = conflicting or failed
        print(f"  [X] {utterance}（{kind}）：{note}")
        for outcome in sorted(seen[utterance]):
            print(f"      {outcome[:100]}")

    if conflicting:
        print("\n  同一句话执行出了不同的动作——这是必须处理的。")
        return 1
    print(
        "\n  没有出现「同一句话执行出不同动作」的情况：\n"
        "  不稳定只表现为「这一轮没听懂」，演示时改用规则能直接认出的说法即可。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
