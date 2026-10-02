"""影子分类（scripts/shadow_classifier.py，2026-09-29）：只记录、不改回答。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from scripts.shadow_classifier import ShadowClassifier, compare, rule_channels
from service.assistant.models import Answer, AnswerSource, Facts, Intent, IntentKind

MOMENT = datetime(2026, 9, 29, 17, 0, 0)


class FakeClient:
    """一次只接一个请求；``finish(reply)`` 之前一直忙。"""

    def __init__(self) -> None:
        self.submitted: list[str] = []
        self.cancelled = 0
        self._busy = False
        self._reply: str | None = None

    def submit(self, prompt: str, system: str = "") -> bool:
        if self._busy:
            return False
        self.submitted.append(prompt)
        self._busy = True
        return True

    def finish(self, reply: str) -> None:
        self._reply = reply
        self._busy = False

    def poll(self) -> str | None:
        reply, self._reply = self._reply, None
        return reply

    def is_busy(self) -> bool:
        return self._busy

    def cancel(self) -> None:
        self.cancelled += 1
        self._busy = False


def _answer(
    kind: IntentKind, *channels: str, source: AnswerSource = AnswerSource.TEMPLATE
) -> Answer:
    facts = tuple(Facts(kind=kind, channel=c) for c in channels)
    return Answer(
        text="…",
        source=source,
        intent=Intent(kind=kind, channel=channels[0] if channels else None),
        all_facts=facts if len(facts) > 1 else (),
    )


def _shadow(
    tmp_path: Path, busy: list[bool] | None = None
) -> tuple[ShadowClassifier, FakeClient]:
    client = FakeClient()
    flag = busy if busy is not None else [False]
    shadow = ShadowClassifier(
        client, lambda: flag[0], log_dir=tmp_path, clock=lambda: MOMENT
    )
    return shadow, client


def _records(tmp_path: Path) -> list[dict]:
    path = tmp_path / "shadow_20260929.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_compare_names_the_kinds_of_disagreement() -> None:
    cv = IntentKind.CURRENT_VALUE
    both = (Intent(cv, "temperature"), Intent(cv, "humidity"))
    assert compare(cv, ["humidity"], both) == "model_more_channels"
    assert compare(cv, ["temperature", "humidity"], both) == "agree"
    assert (
        compare(cv, ["temperature", "humidity"], (Intent(cv, "humidity"),))
        == "model_fewer_channels"
    )
    assert compare(cv, ["noise"], (Intent(cv, "humidity"),)) == "channel_differs"
    assert (
        compare(cv, ["noise"], (Intent(IntentKind.MAXIMUM, "noise"),)) == "kind_differs"
    )
    assert (
        compare(
            cv,
            ["noise"],
            (Intent(cv, "noise"), Intent(IntentKind.ALARM_STATE, "noise")),
        )
        == "model_unsure"
    )
    assert compare(cv, ["noise"], ()) == "model_unknown"


def test_rule_channels_reads_every_expanded_part() -> None:
    assert rule_channels(
        _answer(IntentKind.CURRENT_VALUE, "temperature", "humidity")
    ) == ["temperature", "humidity"]
    assert rule_channels(_answer(IntentKind.FAN_STATE)) == []


def test_a_rule_answered_question_is_classified_and_logged(tmp_path: Path) -> None:
    shadow, client = _shadow(tmp_path)
    shadow.offer("温湿度多少", _answer(IntentKind.CURRENT_VALUE, "humidity"))
    shadow.step()
    assert len(client.submitted) == 1 and "温湿度多少" in client.submitted[0]
    client.finish("current_value temperature humidity")
    shadow.step()
    [record] = _records(tmp_path)
    assert record["verdict"] == "model_more_channels"
    assert record["rule"] == {"kind": "current_value", "channels": ["humidity"]}
    assert {m["channel"] for m in record["model"]} == {"temperature", "humidity"}


def test_it_waits_while_the_assistant_is_using_the_model(tmp_path: Path) -> None:
    busy = [True]
    shadow, client = _shadow(tmp_path, busy)
    shadow.offer("湿度多少", _answer(IntentKind.CURRENT_VALUE, "humidity"))
    shadow.step()
    assert client.submitted == []
    busy[0] = False
    shadow.step()
    assert len(client.submitted) == 1


def test_a_new_question_cancels_the_running_classification(tmp_path: Path) -> None:
    # 一次分类约 4.4 s；用户接着问时必须把模型让出来。
    shadow, client = _shadow(tmp_path)
    shadow.offer("湿度多少", _answer(IntentKind.CURRENT_VALUE, "humidity"))
    shadow.step()
    shadow.offer("开风扇", _answer(IntentKind.FAN_ON, source=AnswerSource.TEMPLATE))
    shadow.step()
    assert client.cancelled == 1
    assert [r["outcome"] for r in _records(tmp_path)] == ["superseded"]
    shadow.step()
    assert len(client.submitted) == 1  # the instruction is not shadowed


def test_only_rule_decided_questions_are_shadowed(tmp_path: Path) -> None:
    shadow, client = _shadow(tmp_path)
    for answer in (
        _answer(IntentKind.CURRENT_VALUE, "noise", source=AnswerSource.PENDING),
        _answer(IntentKind.CURRENT_VALUE, "noise", source=AnswerSource.FALLBACK),
        _answer(IntentKind.FAN_OFF),
        None,
    ):
        shadow.offer("…", answer)
        shadow.step()
    assert client.submitted == []


def test_only_the_latest_queued_question_is_kept(tmp_path: Path) -> None:
    busy = [True]
    shadow, client = _shadow(tmp_path, busy)
    shadow.offer("湿度多少", _answer(IntentKind.CURRENT_VALUE, "humidity"))
    shadow.offer("噪声多少", _answer(IntentKind.CURRENT_VALUE, "noise"))
    busy[0] = False
    shadow.step()
    assert len(client.submitted) == 1 and "噪声多少" in client.submitted[0]
    assert [r["question"] for r in _records(tmp_path)] == ["湿度多少"]
