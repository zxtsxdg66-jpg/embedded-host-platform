"""评测脚本本身的测试：题库不能悄悄退化，判分口径不能松。

跑的是 ``--no-llm`` 模式（秒级、无外部依赖），它量的是规则覆盖率——
接模型那一趟需要本地 Ollama，不适合放进单元测试。
"""

from __future__ import annotations

import pytest

from scripts.assistant_benchmark import (
    BANK,
    INSTRUCTION,
    OUT_OF_SCOPE,
    QUESTION,
    _grade,
    main,
)
from service.assistant.models import Answer, AnswerSource, Facts, Intent, IntentKind


def _answer(kind: IntentKind, channel: str | None = None, applied: bool | None = None):
    return Answer(
        text="",
        source=AnswerSource.TEMPLATE,
        intent=Intent(kind=kind, channel=channel),
        facts=Facts(kind=kind, applied=applied),
    )


# -- 判分口径 ----------------------------------------------------------


def test_an_instruction_must_actually_have_been_carried_out() -> None:
    """认出来却没落到设置上等于没做——判分必须看 applied，而不只看意图。"""
    understood_only = _answer(IntentKind.FAN_ON, applied=False)
    carried_out = _answer(IntentKind.FAN_ON, applied=True)

    assert not _grade(INSTRUCTION, "fan_on", None, understood_only)
    assert _grade(INSTRUCTION, "fan_on", None, carried_out)


def test_out_of_scope_counts_as_correct_only_when_refused() -> None:
    """答出任何具体内容都意味着它给自己编了个话题。"""
    refused = _answer(IntentKind.HELP)
    answered = _answer(IntentKind.CURRENT_VALUE, "temperature")

    assert _grade(OUT_OF_SCOPE, None, None, refused)
    assert not _grade(OUT_OF_SCOPE, None, None, answered)


def test_a_question_must_match_both_kind_and_channel() -> None:
    """通道答错和意图答错一样是错的：把湿度问题答成温度，数字是真的但答非所问。"""
    right = _answer(IntentKind.MAXIMUM, "noise")
    wrong_channel = _answer(IntentKind.MAXIMUM, "temperature")
    wrong_kind = _answer(IntentKind.CURRENT_VALUE, "noise")

    assert _grade(QUESTION, "maximum", "noise", right)
    assert not _grade(QUESTION, "maximum", "noise", wrong_channel)
    assert not _grade(QUESTION, "maximum", "noise", wrong_kind)


# -- 题库 --------------------------------------------------------------


def test_bank_covers_all_three_kinds_with_refusals_included() -> None:
    """只测顺利路径的评测发现不了一个"对什么都说好"的系统。"""
    kinds = {kind for _, kind, _, _ in BANK}
    refusals = [q for q, kind, want, _ in BANK if kind == OUT_OF_SCOPE and want is None]

    assert kinds == {QUESTION, INSTRUCTION, OUT_OF_SCOPE}
    assert len(refusals) >= 5


def test_bank_has_no_duplicate_questions() -> None:
    """重复的问句会让成功率被同一句话加权两次。"""
    questions = [q for q, _, _, _ in BANK]

    assert len(questions) == len(set(questions))


def test_every_instruction_expects_a_control_intent() -> None:
    control = {"fan_on", "fan_off", "fan_auto", "set_vent_threshold"}
    instructions = [want for _, kind, want, _ in BANK if kind == INSTRUCTION]

    assert instructions
    assert set(instructions) <= control


# -- 端到端（不接模型） ------------------------------------------------


def test_rules_alone_already_answer_most_of_the_bank(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """规则覆盖率是这套问答里唯一零延迟且每次一致的部分，掉下来要能被发现。"""
    exit_code = main(["--no-llm", "--wait", "0"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "规则命中" in out

    graded = [line for line in out.splitlines() if line.startswith(("OK", "NG"))]
    passed = [line for line in graded if line.startswith("OK")]
    assert len(graded) == len(BANK)
    assert len(passed) / len(graded) >= 0.70


def test_a_rules_only_run_never_reports_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """不接模型时口语说法本就该落到帮助文案，据此判失败只会制造噪音。"""
    assert main(["--no-llm", "--wait", "0"]) == 0
    assert "不据此判定失败" in capsys.readouterr().out
