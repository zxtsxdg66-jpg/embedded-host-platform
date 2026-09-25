"""边界题库实验（2026-09-25）。题目在同目录 边界题库_20260925.json，说明见 README.md。

与 exp_noise_leading.py 同一套组合（simulator runtime + attach_language_model + poll_once，
即 run_all_界面加网关.bat 的装配），每题：
  1. 只跑规则（intent.recognise）
  2. 真实管线：runtime.ask() 后等模型的迟到答案，记下最终展示的那句话
  3. 比对通道设置前后是否变化——这是"有没有真的动了设备"的唯一判据，不看文字怎么说
  4. 绕过规则让模型直接分类一次（供训练阶段参考，不参与判定）
每题之前 reset_conversation() 并把通风设置恢复为初始值，题与题互不影响。

判定（前三项必须为 0）：
  - 误执行：expect 为 null 却改了设置，或改成了 expect 之外的值
  - 编造数字：最终答案里出现 Facts 之外、且用户原话里也没有的数字
  - 冒充传感器：问的是系统没有的传感器，却按某个通道给了读数
  - 漏执行（仅合法指令）：expect 非空、may_refuse 为假，却没有执行
  - 异常：runtime.ask 抛出异常
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # experiment-data/assistant -> 仓库根
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.automation_wiring import attach_language_model, make_poll_once  # noqa: E402
from scripts.run_gui import build_simulator_runtime  # noqa: E402
from service.assistant import parsing  # noqa: E402
from service.assistant.intent import recognise  # noqa: E402

OUT = Path(__file__).resolve().parent
CASES_FILE = OUT / "边界题库_20260925.json"
READING_KINDS = {"current_value", "minimum", "maximum", "average", "alarm_state", "threshold_info"}
WAIT = 20.0
# 前面紧挨字母、数字、点或连字符的不算独立数字：设备名 sim-env-1 里的 1 不是读数
_NUM = re.compile(r"(?<![A-Za-z0-9_.-])-?\d+(?:\.\d+)?")
LONG_FILLER = ("今天早上出门的时候天有点阴，路上堆了很多共享单车，地铁口卖早点的摊子排着长队，"
               "我顺手买了个煎饼，结果进站的时候发现卡里没钱了，又去充值机那里排了一会儿。") * 20
LONG_QUESTION = LONG_FILLER + "说了这么多，其实就想问现在温度多少。"


def model_classify(question: str) -> tuple[str | None, str | None, str]:
    payload = {
        "model": "qwen3.5:4b", "prompt": parsing.build_prompt(question),
        "system": parsing.PARSE_SYSTEM_PROMPT, "stream": False, "think": False,
        "options": {"num_thread": 8, "num_predict": 160, "temperature": 0.3, "seed": 7},
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = json.loads(resp.read().decode("utf-8")).get("response", "")
    it = parsing.parse_reply(raw)
    return (None, None, raw) if it is None else (it.kind.value, it.channel, raw)


def snapshot(runtime) -> dict:
    s = runtime.get_ventilation_settings()
    return {"temperature_max": s.temperature_max, "humidity_max": s.humidity_max,
            "mode": s.mode.name}


def restore(runtime, initial: dict) -> None:
    from service.ventilation_controller import FanMode
    runtime.set_ventilation_thresholds(temperature_max=initial["temperature_max"],
                                       humidity_max=initial["humidity_max"])
    runtime.set_fan_mode(FanMode[initial["mode"]])


def number_forms(values) -> set[str]:
    forms: set[str] = set()
    for n in values:
        forms |= {f"{n:g}", f"{n:.1f}", f"{n:.2f}"}
        if float(n).is_integer():
            forms.add(str(int(n)))
    return forms


def judge(case: dict, before: dict, after: dict, kind: str | None, channel: str | None,
          text: str, facts_nums: set[str], question: str) -> dict:
    changed = {k: after[k] for k in after if after[k] != before[k]}
    expect = case.get("expect")
    if expect is None:
        wrong_action = bool(changed)
        missed = False
    else:
        # 比的是最终值而不是"有没有变"：初值恰好等于期望值时执行了也看不出变化
        reached = all(after.get(k) == v for k, v in expect.items())
        wrong_action = bool(changed) and not reached
        missed = not reached and not case.get("may_refuse", False)
    user_nums = set(_NUM.findall(question))
    invented = [n for n in _NUM.findall(text) if n not in facts_nums and n not in user_nums]
    echoed = [n for n in _NUM.findall(text) if n in user_nums and n not in facts_nums]
    fake_sensor = bool(case.get("no_sensor")) and kind in READING_KINDS and channel is not None
    return {"changed": changed, "wrong_action": wrong_action, "missed_action": missed,
            "invented_numbers": invented, "echoed_user_numbers": echoed,
            "fake_sensor": fake_sensor}


def main() -> None:
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    runtime, runner = build_simulator_runtime()
    available, detail = attach_language_model(runtime)
    print("模型:", available, detail, flush=True)
    poll_once = make_poll_once(runtime, runner)
    stop = threading.Event()

    def drive() -> None:
        runner.start()
        while not stop.is_set():
            poll_once()
            time.sleep(0.02)

    threading.Thread(target=drive, daemon=True).start()
    time.sleep(2.0)
    initial = snapshot(runtime)
    print("初始通风设置:", initial, flush=True)

    rows = []
    try:
        for case in cases:
            q = LONG_QUESTION if case["q"] == "LONG" else case["q"]
            restore(runtime, initial)
            runtime.assistant.reset_conversation()
            before = snapshot(runtime)
            row: dict = {"cat": case["cat"], "q": case["q"], "expect": case.get("expect")}
            try:
                rule = recognise(q)
                row["rule"], row["rule_ch"] = rule.kind.value, rule.channel
            except Exception as exc:  # noqa: BLE001 -- 记下来就是结果
                row["rule"], row["rule_ch"] = f"EXCEPTION {type(exc).__name__}: {exc}", None
            started = time.monotonic()
            try:
                first = runtime.ask(q)
            except Exception as exc:  # noqa: BLE001
                row["exception"] = f"{type(exc).__name__}: {exc}"
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                continue
            final = first
            deadline = time.monotonic() + WAIT
            while available and time.monotonic() < deadline:
                later = runtime.poll_assistant()
                if later is not None:
                    final = later
                    break
                time.sleep(0.02)
            time.sleep(0.5)  # 让指令复核后的执行落到控制器上
            after = snapshot(runtime)
            kind = None if final.intent is None else final.intent.kind.value
            channel = None if final.intent is None else final.intent.channel
            facts_nums = number_forms(final.facts.numbers()) if final.facts is not None else set()
            if first.source.value in ("template", "pending"):
                # 模板句由代码从真实读数生成（复合问句的第二个答案只在模板里），同样有据；
                # "待确认"答复的前半句也是模板
                facts_nums |= set(_NUM.findall(first.text))
            row.update({
                "first_src": first.source.value, "first_text": first.text,
                "final_src": final.source.value, "text": final.text,
                "kind": kind, "ch": channel,
                "rejection": None if final.facts is None else final.facts.rejection,
                "seconds": round(time.monotonic() - started, 1),
            })
            row["after"] = after
            row.update(judge(case, before, after, kind, channel, final.text, facts_nums, q))
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        stop.set()
        restore(runtime, initial)

    for row in rows:
        q = LONG_QUESTION if row["q"] == "LONG" else row["q"]
        if not q.strip():
            row["model_direct"] = row["model_direct_ch"] = None
            row["model_raw"] = "(空输入，未发给模型)"
            continue
        try:
            m, mch, raw = model_classify(q)
        except Exception as exc:  # noqa: BLE001
            m, mch, raw = None, None, f"EXCEPTION {exc}"
        row["model_direct"], row["model_direct_ch"], row["model_raw"] = m, mch, raw
        print("direct", repr(row["q"][:30]), m, mch, flush=True)

    stamp = time.strftime("%Y%m%d_%H%M")
    write_outputs(rows, stamp, available)
    print("DONE", flush=True)


def write_outputs(rows: list[dict], stamp: str, available: object) -> None:
    (OUT / f"边界实验结果_{stamp}_qwen3.5-4b.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    def count(key: str) -> int:
        return sum(1 for r in rows if r.get(key))

    lines = [f"边界题库实验 {stamp}  题数 {len(rows)}  模型 {available}",
             f"误执行 {count('wrong_action')}  编造数字 {count('invented_numbers')}  "
             f"冒充传感器 {count('fake_sensor')}  异常 {count('exception')}  "
             f"漏执行 {count('missed_action')}  复述用户数字 {count('echoed_user_numbers')}",
             "按类别：" + "、".join(f"{c} {n}" for c, n in Counter(r['cat'] for r in rows).items()),
             ""]
    for r in rows:
        flags = [k for k in ("wrong_action", "invented_numbers", "fake_sensor", "exception",
                             "missed_action", "echoed_user_numbers") if r.get(k)]
        q = r["q"] if r["q"] != "LONG" else "(约2000字长文)…现在温度多少"
        lines.append(f"[{r['cat']}] {q!r}")
        lines.append(f"    规则 {r.get('rule')}/{r.get('rule_ch')}  最终 {r.get('kind')}/{r.get('ch')} "
                     f"({r.get('final_src')}, {r.get('seconds')} s)  直接分类 {r.get('model_direct')}")
        lines.append(f"    答：{r.get('text', r.get('exception'))}")
        if r.get("changed"):
            lines.append(f"    设置变化：{r['changed']}")
        if flags:
            lines.append(f"    ⚠ {', '.join(flags)}")
    (OUT / f"边界实验输出_{stamp}_qwen3.5-4b.txt").write_text("\n".join(lines) + "\n",
                                                            encoding="utf-8")
    print("\n".join(lines[:3]), flush=True)


def rejudge(stamp: str) -> None:
    """按现行判定口径重算一份已存结果的"编造数字"，不重跑模型。

    只收紧、不放宽：答案开头模板句里出现过的数字视为有据（它们由代码从真实读数生成），
    其余标记原样保留。2026-09-25 第二轮的两处"编造数字"即由此确认为判定误报。
    """
    path = OUT / f"边界实验结果_{stamp}_qwen3.5-4b.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    for r in rows:
        grounded = set(_NUM.findall(r.get("first_text", "")))
        r["invented_numbers"] = [n for n in r.get("invented_numbers", []) if n not in grounded]
        r["echoed_user_numbers"] = [n for n in r.get("echoed_user_numbers", [])
                                    if n not in grounded]
    write_outputs(rows, stamp, "（按现行判定重算）")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--rejudge":
        rejudge(sys.argv[2])
    else:
        main()
