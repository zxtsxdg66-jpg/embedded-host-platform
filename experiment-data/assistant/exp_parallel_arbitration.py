"""离线推演：提问也让规则与模型并行判定，不一致按模型答（2026-10-01）。

用户提议"模板与模型理解并行，出口做校验，首字慢一些可以接受"。出口的五道检查只核
"数字有没有出处"，分不出两种理解谁对，所以并行之后中间需要一条裁决。用户定的裁决是
**不一致就按模型答**，本脚本在不改 ``src/`` 的前提下估算它的效果：

1. 规则侧：用现行代码、不接模型的 ``Assistant`` 逐句作答，取它实际答了什么意图、
   哪几个通道（多通道展开取 ``all_facts``，与影子分类同一取法）；
2. 模型侧：用与线上相同的分类提示词与采样参数（``parsing.PARSE_SYSTEM_PROMPT``、
   温度 0.3），逐句让本地模型独立分类，``parsing.parse_candidates`` 解析；
3. 按三种管线判分，题库与原实验相同：
   - **现行**：规则判出提问就用规则；规则认不出才用模型（与线上一致）；
   - **并行·按模型**：规则判出的提问也看模型，两边不一致时采用模型的判定；
   - **并行·补全**：只在"同一问法、模型认出的通道更多"时取并集，其余仍按规则
     （即 docs/decisions/03-intent.md 影子分类一节提到的"只补通道"，作对照）。

裁决的硬约束（三种管线都守）：**模型只能把提问改判成另一种提问**——模型判成指令时不执行、
仍按规则答；规则判成指令、拒绝、或问的是本次运行之外的时段（``past_scoped``）时，模型不参与。
指令方向维持现状（规则与模型一致才执行），不在本推演范围。

模型的原始回复存进 ``并行裁决推演_<时间>_<模型>.json``，``--replay`` 可只重算判分。

用法::

    python experiment-data/assistant/exp_parallel_arbitration.py
    python experiment-data/assistant/exp_parallel_arbitration.py --replay 并行裁决推演_xxx.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from exp_noise_leading import CASES as ROBUST_CASES  # noqa: E402
from scripts.assistant_benchmark import BANK, INSTRUCTION, OUT_OF_SCOPE  # noqa: E402
from scripts.shadow_classifier import SHADOWED_KINDS, compare, rule_channels  # noqa: E402
from service.assistant import parsing  # noqa: E402
from service.assistant.assistant import Assistant  # noqa: E402
from service.assistant.control import CONTROL_KINDS  # noqa: E402
from service.data_models import DataPoint  # noqa: E402
from service.sensor_data_processor import SensorDataProcessor  # noqa: E402
from service.ventilation_controller import VentilationController  # noqa: E402

MODEL = "qwen3.5:4b"
QUESTION_KINDS = {k.value for k in SHADOWED_KINDS}
CONTROL = {k.value for k in CONTROL_KINDS}
READINGS = {"temperature": [24.8, 25.2], "humidity": [61.0, 62.0], "noise": [44.0, 45.3]}


# ---- 题库 -------------------------------------------------------------------


def load_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in json.loads((HERE / "留出题库_20260914.json").read_text(encoding="utf-8")):
        unknown = row["label"] == "unknown"
        items.append({"set": "留出148", "q": row["q"],
                      "ok": set() if unknown else {row["label"]},
                      "ch": row["channel"], "out": unknown})
    for q, cat, kind, ch in BANK:
        items.append({"set": "题库87", "q": q, "ok": set() if cat == OUT_OF_SCOPE else {kind},
                      "ch": ch, "out": cat == OUT_OF_SCOPE, "cmd": cat == INSTRUCTION})
    for _cat, q, ok_kinds, ch, _must_not_act, _nums in ROBUST_CASES:
        items.append({"set": "鲁棒32", "q": q, "ok": {k for k in ok_kinds if k}, "ch": ch,
                      "out": not any(ok_kinds)})
    boundary = json.loads((HERE / "边界题库_20260925.json").read_text(encoding="utf-8"))
    rows = next(v for v in boundary.values() if isinstance(v, list))
    for row in rows:
        items.append({"set": "边界75", "q": row["q"], "ok": None, "ch": None, "out": False})
    return items


# ---- 规则侧 -----------------------------------------------------------------


def rule_side(question: str) -> dict[str, Any]:
    processor = SensorDataProcessor()
    for channel, values in READINGS.items():
        for value in values:
            processor.handle_data_point(DataPoint(device_id="dev-1", channel=channel, value=value))
    assistant = Assistant(processor, lambda: ["dev-1"], ventilation=VentilationController())
    answer = assistant.ask(question)
    intent = answer.intent
    return {
        "kind": intent.kind.value if intent else None,
        "chs": rule_channels(answer),
        "past": bool(intent and intent.past_scoped),
        "source": answer.source.value if hasattr(answer.source, "value") else str(answer.source),
    }


# ---- 模型侧 -----------------------------------------------------------------


def model_side(question: str) -> tuple[str, float]:
    payload = {
        "model": MODEL,
        "prompt": parsing.build_prompt(question),
        "system": parsing.PARSE_SYSTEM_PROMPT,
        "stream": False,
        "think": False,
        "options": {"num_thread": 8, "num_predict": 160, "temperature": 0.3},
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("response", ""), time.monotonic() - started


# ---- 裁决与判分 ---------------------------------------------------------------


def decide(rule: dict[str, Any], raw: str, policy: str) -> tuple[str | None, list[str], str]:
    """返回 (意图, 通道, 归类)。归类即 shadow_classifier.compare 的结果或说明。"""
    candidates = parsing.parse_candidates(raw)
    kind = rule["kind"]
    if kind in QUESTION_KINDS and not rule["past"]:
        from service.assistant.models import IntentKind

        verdict = compare(IntentKind(kind), rule["chs"], candidates)
        if policy == "current" or verdict in ("agree", "model_unknown", "model_unsure"):
            return kind, rule["chs"], verdict
        model_kind = candidates[0].kind.value
        model_chs = list(dict.fromkeys(c.channel for c in candidates if c.channel))
        if model_kind not in QUESTION_KINDS:
            return kind, rule["chs"], verdict + "(模型判成非提问，不采纳)"
        if policy == "model":
            return model_kind, model_chs, verdict
        if policy == "union" and verdict == "model_more_channels":
            return kind, model_chs, verdict
        return kind, rule["chs"], verdict
    if kind == "help":
        # 规则认不出：三种管线都与线上一致，交给模型；模型判成指令时线上会反问，这里记为未执行
        if candidates and len({c.kind for c in candidates}) == 1:
            ck = candidates[0].kind.value
            if ck in QUESTION_KINDS:
                return ck, list(dict.fromkeys(c.channel for c in candidates if c.channel)), "rule_help"
        return "help", [], "rule_help"
    return kind, rule["chs"], "rule_final"


def grade(item: dict[str, Any], kind: str | None, chs: list[str]) -> bool | None:
    if item["ok"] is None:
        return None
    if item["out"]:
        return kind not in QUESTION_KINDS and kind not in CONTROL
    if kind not in item["ok"]:
        return False
    return item["ch"] is None or set(chs) == {item["ch"]}


# ---- 主程序 -----------------------------------------------------------------


def run(replay: Path | None) -> Path:
    items = load_items()
    if replay:
        saved = {r["q"]: r for r in json.loads(replay.read_text(encoding="utf-8"))["rows"]}
    rows = []
    for i, item in enumerate(items, 1):
        rule = rule_side(item["q"])
        if replay:
            raw, secs = saved[item["q"]]["raw"], saved[item["q"]]["s"]
        else:
            raw, secs = model_side(item["q"])
            print(f"[{i}/{len(items)}] {secs:4.1f}s {item['q'][:24]} -> {raw.strip()[:40]!r}", flush=True)
        row: dict[str, Any] = {"set": item["set"], "q": item["q"], "expect": sorted(item["ok"] or []),
                               "expect_ch": item["ch"], "rule": rule, "raw": raw, "s": round(secs, 2)}
        for policy in ("current", "model", "union"):
            k, c, v = decide(rule, raw, policy)
            row[policy] = {"kind": k, "chs": c, "verdict": v, "ok": grade(item, k, c)}
        rows.append(row)
    out = replay or HERE / f"并行裁决推演_{datetime.now():%Y%m%d_%H%M}_{MODEL.replace(':', '-')}.json"
    out.write_text(json.dumps({"model": MODEL, "rows": rows}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    summarise(rows)
    return out


def summarise(rows: list[dict[str, Any]]) -> None:
    print("\n== 判分（规则判出的提问才可能被改判；边界 75 句无意图标注，只看改判了哪些）==")
    for name in ("留出148", "题库87", "鲁棒32", "边界75"):
        sub = [r for r in rows if r["set"] == name]
        line = [f"{name}"]
        for policy in ("current", "model", "union"):
            graded = [r[policy]["ok"] for r in sub if r[policy]["ok"] is not None]
            if graded:
                line.append(f"{policy} {sum(graded)}/{len(graded)}")
        changed = [r for r in sub if (r["model"]["kind"], r["model"]["chs"])
                   != (r["current"]["kind"], r["current"]["chs"])]
        fixed = sum(1 for r in changed if r["model"]["ok"] and r["current"]["ok"] is False)
        broke = sum(1 for r in changed if r["current"]["ok"] and r["model"]["ok"] is False)
        line.append(f"按模型改判 {len(changed)} 句（改对 {fixed}、改错 {broke}）")
        print("  " + "  ".join(line))
    secs = [r["s"] for r in rows]
    print(f"\n模型分类耗时：中位数 {st.median(secs):.2f} s，最长 {max(secs):.2f} s（即首字要多等的时间）")
    print("\n== 按模型改判的逐句 ==")
    for r in rows:
        if (r["model"]["kind"], r["model"]["chs"]) != (r["current"]["kind"], r["current"]["chs"]):
            mark = {True: "✔", False: "✘", None: "?"}
            print(f"  [{r['set']}] {r['q']}\n      现行 {r['current']['kind']} {r['current']['chs']} "
                  f"{mark[r['current']['ok']]}  →  按模型 {r['model']['kind']} {r['model']['chs']} "
                  f"{mark[r['model']['ok']]}  ({r['model']['verdict']})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    target = args.replay if args.replay is None or args.replay.is_absolute() else HERE / args.replay
    print(f"已写入 {run(target)}")
