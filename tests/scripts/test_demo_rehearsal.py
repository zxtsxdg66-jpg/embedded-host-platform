"""The rehearsal script itself, exercised without a model attached.

Runs the whole demonstration script through the real composition in
``--no-llm`` mode, which is fast, deterministic and needs nothing
installed. What it proves is that the rehearsal tool still works -- the
tool whose job is to catch the things this suite cannot.

It also pins the script's *contents*: an utterance list that quietly lost
its refusal cases would still pass every other test in the project while
turning the rehearsal into a happy-path demo.
"""

from __future__ import annotations

import pytest

from scripts.demo_rehearsal import (
    INSTRUCTION,
    OUT_OF_SCOPE,
    QUESTION,
    UTTERANCES,
    _describe,
    main,
)


def test_a_rehearsal_without_a_model_is_stable_and_passes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two identical rounds, rules and templates only. Anything unstable
    here would be a defect in the rules, not in the model."""
    exit_code = main(["--no-llm", "--rounds", "2", "--wait", "0"])

    assert exit_code == 0
    assert "全部一致" in capsys.readouterr().out


def test_every_utterance_is_answered_or_refused_but_never_crashes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The script is typed at the system verbatim; a phrasing that raised
    would take the demonstration down with it."""
    main(["--no-llm", "--rounds", "1", "--wait", "0"])

    out = capsys.readouterr().out
    for utterance, _ in UTTERANCES:
        assert utterance in out


def test_the_script_still_covers_all_three_kinds() -> None:
    kinds = {kind for _, kind in UTTERANCES}

    assert kinds == {QUESTION, INSTRUCTION, OUT_OF_SCOPE}


def test_the_script_still_contains_utterances_that_must_be_refused() -> None:
    """A rehearsal that only exercises the happy path would not notice a
    system that had started saying yes to everything."""
    utterances = [text for text, _ in UTTERANCES]

    assert "通风温度阈值调到 300 度" in utterances  # 超量程
    assert "把通风温度阈值调低一点" in utterances  # 没给数值
    assert "帮我订张票" in utterances  # 系统范围之外


# -- how instability is judged ------------------------------------------------
#
# This is the tool's own judgement, and getting it wrong in either
# direction ruins it: calling a decline a failure trains the reader to
# ignore the report, and calling two different actions "just variation"
# hides the one thing worth catching.


def test_two_different_actions_from_one_sentence_is_a_failure() -> None:
    note, failed = _describe(
        {"model_intent|fan_on|applied=True", "model_intent|fan_off|applied=True"}
    )

    assert failed
    assert "不同的动作" in note


def test_understood_once_and_declined_once_is_reported_not_failed() -> None:
    """The system declined; it did not act wrongly. That is the ordinary
    behaviour of a 4B model on colloquial phrasing."""
    note, failed = _describe(
        {"fallback|help|applied=None", "model_intent|current_value|applied=None"}
    )

    assert not failed
    assert "拒绝" in note


def test_the_same_understanding_worded_two_ways_is_not_instability() -> None:
    """A rephrasing that arrived in one round and not the other says
    nothing about how the sentence was understood."""
    note, failed = _describe(
        {"template|fan_state|applied=None", "model|fan_state|applied=None"}
    )

    assert not failed
    assert "理解一致" in note


def test_two_different_questions_answered_is_reported_not_failed() -> None:
    note, failed = _describe(
        {"model_intent|maximum|applied=None", "model_intent|current_value|applied=None"}
    )

    assert not failed
    assert "真实读数" in note

