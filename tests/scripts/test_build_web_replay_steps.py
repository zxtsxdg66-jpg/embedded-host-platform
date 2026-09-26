"""build_web_replay 的实时流程部分：没录完整的时间线不许进页面（2026-09-26）。

回放会把录下的步骤按原始耗时重演。一条没收尾的时间线在页面上会停在半路，
看起来像系统卡住了——而那并不是系统的行为，是录制没录完。所以生成时就拦下。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import build_web_replay


def _step(kind: str, seq: int, at_ms: int, **over: object) -> dict:
    step = {
        "type": "assistant_step", "question_id": 0, "seq": seq, "at_ms": at_ms,
        "kind": kind, "text": "", "job": "", "note": "", "intent": None,
        "facts": None, "source": None, "checks": [], "verdict": None, "final": False,
    }
    step.update(over)
    return step


def _row(question: str, steps: list[dict], complete: bool = True) -> dict:
    final = {"text": "温度现在是 26.6℃。", "source": "template", "question_id": 1,
             "intent": None, "facts": None, "trace": []}
    return {"label": "取数", "question": question, "first": dict(final),
            "final": final, "steps": steps, "complete": complete}


def _write(tmp_path: Path, rows: list[dict], hot: list[dict] | None = None) -> None:
    record = {"录制时间": "20260926_1453", "现行配置_温度0.3": rows,
              "对照_温度0.8": hot or []}
    (tmp_path / "实时流程录制_20260926_1453_qwen3.5-4b.json").write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8"
    )


_GOOD = [
    _step("received", 1, 0, text="现在温度多少"),
    _step("answered", 2, 3, text="温度现在是 26.6℃。", source="template", final=True),
]


def test_a_complete_timeline_becomes_an_item(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(build_web_replay, "BASELINE_DIR", tmp_path)
    _write(tmp_path, [_row("现在温度多少", _GOOD)], [_row("吵不吵", _GOOD)])

    items = build_web_replay.build_step_items()

    assert [i["config"] for i in items] == ["实时流程", "实时流程 · 采样温度 0.8"]
    assert items[0]["steps"] == _GOOD
    assert items[0]["first"]["text"] == "温度现在是 26.6℃。"
    assert "0.8" in items[1]["recorded"]


def test_an_unfinished_recording_fails_the_build(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(build_web_replay, "BASELINE_DIR", tmp_path)
    _write(tmp_path, [_row("现在温度多少", _GOOD, complete=False)])

    with pytest.raises(ValueError, match="没有录完整"):
        build_web_replay.build_step_items()


def test_a_timeline_without_a_final_answer_fails_the_build(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(build_web_replay, "BASELINE_DIR", tmp_path)
    cut = [_GOOD[0], _step("answered", 2, 3, final=False)]
    _write(tmp_path, [_row("现在温度多少", cut)])

    with pytest.raises(ValueError, match="首尾不完整"):
        build_web_replay.build_step_items()


def test_the_committed_recording_builds() -> None:
    """仓库里那份录制本身必须能过上面的检查。"""
    items = build_web_replay.build_step_items()
    assert items
    assert all(i["steps"][0]["kind"] == "received" for i in items)
