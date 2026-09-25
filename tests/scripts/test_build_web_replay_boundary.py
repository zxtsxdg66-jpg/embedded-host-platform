"""build_web_replay 的边界题部分：页面上的结论必须与记录一致。

2026-09-25 把边界题库接进网页问答回放。挑出来展示的每一题都带一个结论
（守住／已知局限／合法指令已执行），结论由记录决定，不由挑选者说了算——
记录与结论对不上时宁可生成失败，也不让页面说一句记录不支持的话。
"""

from __future__ import annotations

import pytest

from scripts.build_web_replay import boundary_items, boundary_summary


def _row(q: str, **over: object) -> dict:
    row = {
        "cat": "否定与撤回", "q": q, "rule": "fan_state", "rule_ch": None,
        "first_src": "template", "first_text": "风扇已停止（自动）。",
        "final_src": "model", "text": "风扇目前停着。", "kind": "fan_state", "ch": None,
        "changed": {}, "wrong_action": False, "fake_sensor": False,
        "invented_numbers": [], "exception": None, "missed_action": False,
    }
    row.update(over)
    return row


def test_a_held_pick_becomes_an_item_with_its_verdict() -> None:
    items = boundary_items(
        [_row("不要关风扇")], [("不要关风扇", "held", "说明")], "记录说明"
    )

    assert len(items) == 1
    item = items[0]
    assert item["config"] == "边界题库"
    assert item["text"] == "风扇目前停着。"
    assert item["first"] == {"text": "风扇已停止（自动）。", "source": "template"}
    assert item["intent"] == {"kind": "FAN_STATE", "channel": None}
    assert item["applied"] is False
    assert item["boundary"]["verdict"] == "held"
    assert item["boundary"]["changed"] == {}
    assert item["recorded"] == "记录说明"


def test_held_is_refused_when_the_record_shows_the_settings_changed() -> None:
    row = _row("不要关风扇", changed={"mode": "MANUAL_OFF"}, wrong_action=True)
    with pytest.raises(ValueError, match="不要关风扇"):
        boundary_items([row], [("不要关风扇", "held", "")], "")


def test_executed_requires_a_change_and_limit_requires_the_flag() -> None:
    with pytest.raises(ValueError):
        boundary_items(
            [_row("通风温度阈值调到28度")],
            [("通风温度阈值调到28度", "executed", "")],
            "",
        )
    with pytest.raises(ValueError):
        boundary_items(
            [_row("二氧化碳浓度超标没")], [("二氧化碳浓度超标没", "limit", "")], ""
        )
    ok = boundary_items(
        [_row("通风温度阈值调到28度", changed={"temperature_max": 28.0}),
         _row("二氧化碳浓度超标没", fake_sensor=True)],
        [("通风温度阈值调到28度", "executed", ""), ("二氧化碳浓度超标没", "limit", "")],
        "",
    )
    assert [i["boundary"]["verdict"] for i in ok] == ["executed", "limit"]
    assert ok[0]["applied"] is True


def test_a_pick_missing_from_the_record_is_an_error() -> None:
    with pytest.raises(ValueError, match="记录里没有"):
        boundary_items([_row("别的问题")], [("不要关风扇", "held", "")], "")


def test_the_summary_counts_the_whole_run() -> None:
    rows = [_row("a"), _row("b", fake_sensor=True), _row("c", wrong_action=True)]
    text = boundary_summary(rows, "20260925_1500")
    assert "3 句" in text
    assert "误执行 1" in text
    assert "问没有的传感器却答了读数 1" in text
