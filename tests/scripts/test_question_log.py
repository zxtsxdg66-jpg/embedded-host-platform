"""问答日志：记真人说过的话，且绝不把问答带下水。

这些用例守的是两件事：**记全**（一问一答配成一条，含迟到的模型改写）与
**记不下来也不出事**（磁盘写不动时问答照常工作）。后者比前者重要——
日志是给日后补题库用的辅助设施，它坏掉不该让系统跟着坏。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.question_log import QuestionLog


@dataclass(frozen=True)
class _FakeKind:
    value: str


@dataclass(frozen=True)
class _FakeIntent:
    kind: _FakeKind
    channel: str | None = None


@dataclass(frozen=True)
class _FakeFacts:
    applied: bool | None = None


@dataclass(frozen=True)
class _FakeSource:
    value: str


@dataclass(frozen=True)
class _FakeAnswer:
    text: str
    source: _FakeSource
    intent: _FakeIntent | None = None
    facts: _FakeFacts | None = None


def _answer(
    text: str = "温度现在是 26.5℃。",
    source: str = "template",
    intent: str | None = "current_value",
    channel: str | None = "temperature",
    applied: bool | None = None,
) -> _FakeAnswer:
    return _FakeAnswer(
        text=text,
        source=_FakeSource(source),
        intent=None if intent is None else _FakeIntent(_FakeKind(intent), channel),
        facts=_FakeFacts(applied),
    )


def _lines(log_dir: Path) -> list[dict[str, Any]]:
    files = sorted(log_dir.glob("*.jsonl"))
    rows: list[dict[str, Any]] = []
    for path in files:
        rows.extend(
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        )
    return rows


# -- 记全 ---------------------------------------------------------------------


def test_question_and_late_answer_become_one_line(tmp_path: Path) -> None:
    """模板答案与几秒后的模型改写属于同一次提问，应当合成一条。"""
    log = QuestionLog(log_dir=tmp_path)

    log.record_question("现在温度多少", _answer())
    log.record_late_answer("现在是 26.5 度，还算舒服。", "model")

    rows = _lines(tmp_path)
    assert len(rows) == 1
    assert rows[0]["question"] == "现在温度多少"
    assert rows[0]["immediate"]["source"] == "template"
    assert rows[0]["immediate"]["intent"] == "current_value"
    assert rows[0]["final"]["source"] == "model"
    assert "late_ms" in rows[0]


def test_a_new_question_flushes_the_previous_one(tmp_path: Path) -> None:
    """新问题进来时，助手已经取消了上一条在飞的改写（见 Assistant._start_rephrasing），
    那一条不会再有结果，必须原样落盘而不是等到天荒地老。"""
    log = QuestionLog(log_dir=tmp_path)

    log.record_question("现在温度多少", _answer())
    log.record_question("湿度呢", _answer(text="湿度现在是 61.0%RH。"))

    rows = _lines(tmp_path)
    assert len(rows) == 1
    assert rows[0]["question"] == "现在温度多少"
    assert "final" not in rows[0]


def test_flush_writes_the_pending_question(tmp_path: Path) -> None:
    log = QuestionLog(log_dir=tmp_path)

    log.record_question("现在温度多少", _answer())
    log.flush()

    assert len(_lines(tmp_path)) == 1


def test_phone_questions_are_marked(tmp_path: Path) -> None:
    """手机与桌面要分得开：同一句话在两端的表现可能不同。"""
    log = QuestionLog(log_dir=tmp_path)

    log.record_question("噪声超标了吗", _answer(intent="alarm_state"), source="phone")
    log.flush()

    assert _lines(tmp_path)[0]["from"] == "phone"


def test_executed_instruction_is_recorded(tmp_path: Path) -> None:
    """误执行是日志最该抓的一类：applied 为真、而问句本不该动设备。"""
    log = QuestionLog(log_dir=tmp_path)

    log.record_question(
        "帮我把风扇打开",
        _answer(text="已把风扇切到手动常开。", intent="fan_on", channel=None,
                applied=True),
    )
    log.flush()

    row = _lines(tmp_path)[0]
    assert row["immediate"]["intent"] == "fan_on"
    assert row["immediate"]["applied"] is True


def test_files_are_split_by_day(tmp_path: Path) -> None:
    """按天分文件，且**按提问时刻归档**。

    只在 ``record_question`` 里取一次时钟，落盘用的是记录自带的时刻——
    否则第二天写盘时，前一天那条会被归进新一天的文件。
    """
    moments = iter([datetime(2026, 9, 17, 10, 0), datetime(2026, 9, 18, 9, 0)])
    log = QuestionLog(log_dir=tmp_path, clock=lambda: next(moments))

    log.record_question("昨天这句", _answer())
    log.record_question("今天这句", _answer())  # 落盘上一条，用的是它自己那天
    log.flush()

    assert sorted(p.name for p in tmp_path.glob("*.jsonl")) == [
        "20260917.jsonl",
        "20260918.jsonl",
    ]


def test_a_late_answer_is_filed_under_the_question_s_day(tmp_path: Path) -> None:
    """跨零点的那一问：提问在 23:59，改写几秒后才回来，已经是第二天。

    这条记录属于昨天——日志是拿来回溯"那天问了什么"的。
    """
    moments = iter([datetime(2026, 9, 17, 23, 59, 58)])
    log = QuestionLog(log_dir=tmp_path, clock=lambda: next(moments))

    log.record_question("跨零点这句", _answer())
    log.record_late_answer("改写后的话", "model")

    assert [p.name for p in tmp_path.glob("*.jsonl")] == ["20260917.jsonl"]


# -- 记不下来也不出事 ---------------------------------------------------------


def test_a_broken_log_never_raises(tmp_path: Path) -> None:
    """日志目录被一个同名文件占住，写入必然失败。

    问答不能因此崩溃——这与"模型缺席时问答照常工作"是同一条原则。
    失败要计数，但不外抛，也不让调用方感知。
    """
    blocked = tmp_path / "occupied"
    blocked.write_text("我是一个文件，不是目录", encoding="utf-8")
    log = QuestionLog(log_dir=blocked)

    log.record_question("现在温度多少", _answer())
    log.record_late_answer("改写后的话", "model")
    log.flush()

    assert log.failures > 0


def test_a_late_answer_without_a_question_is_ignored(tmp_path: Path) -> None:
    """迟到答案总跟着某一次提问；没有挂起的提问说明日志刚起来，静默跳过即可。"""
    log = QuestionLog(log_dir=tmp_path)

    log.record_late_answer("无主的改写", "model")

    assert _lines(tmp_path) == []
    assert log.failures == 0


def test_answer_without_intent_or_facts_still_logs(tmp_path: Path) -> None:
    """反问澄清一类的答案没有 facts，占位答案连 intent 都可能没有。

    这些恰恰是分析时要看的行（"这句没听懂"），不能因为字段缺失就记不下来。
    """
    log = QuestionLog(log_dir=tmp_path)

    log.record_question(
        "帮我订张票", _FakeAnswer(text="这句我没听懂。", source=_FakeSource("fallback"))
    )
    log.flush()

    row = _lines(tmp_path)[0]
    assert row["immediate"]["source"] == "fallback"
    assert row["immediate"]["intent"] is None
