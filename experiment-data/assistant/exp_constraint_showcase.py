"""把"对模型的约束"在真实问答上的样子录下来，供浏览器控制台的问答回放使用。

约束的设计与统计见 docs/decisions/02-llm.md，但读者一直没见过**一次具体的问答里每一层各做了什么**。
本脚本走与正式启动脚本相同的装配（仿真运行时＋`attach_language_model`＋`poll_once`），逐题记录：

- 规则层给出的意图、取数层产出的事实清单；
- 模板渲染出的原句、模型改写的原文；
- 出口检查的判定——采纳，或被哪一道拦下（按 `phrasing.choose` 的顺序逐道复算）；
- 最终交给用户的回答与来源（模板／模型）。

**不改 `src/` 一行**：记录靠在运行时包一层 `phrasing.choose`，只读不改它的判定。

分两组跑：

1. **现行配置**（采样温度 0.3）：取数、错误前提、注入、征询语气、指令、范围外、复合句各一题，
   问句原文取自鲁棒性题库，不重新编写。
2. **较高采样温度 0.8**：读数类问题各问若干遍，目的是录到出口检查**真实拦下**的改写。
   现行配置下它们处于零触发状态，拦截只在这个条件下出现。

两组的数据源都是仿真模式，读数不是现场值；本脚本要展示的是约束的行为，不是读数本身。

用法::

    python experiment-data/assistant/exp_constraint_showcase.py
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from llm.ollama import OllamaClient  # noqa: E402
from scripts.automation_wiring import make_poll_once  # noqa: E402
from scripts.run_gui import build_simulator_runtime  # noqa: E402
from service.assistant import phrasing  # noqa: E402

WAIT_SECONDS = 25.0
WARMUP_CYCLES = 150

_original_choose = phrasing.choose
_trace: list[dict[str, object]] = []


def _verdict(template: str, model: str | None, facts, expanded: bool) -> str:
    """按 ``phrasing.choose`` 的顺序复算是哪一道检查起的作用。只读。"""
    if model is None:
        return "无改写"
    cand = model.strip()
    if len(cand) < 2:
        return "改写为空"
    if not phrasing.numbers_are_grounded(cand, facts):
        return "拦下：接地校验（出现事实里没有的数字）"
    if phrasing._claims_an_alarm(cand, facts):
        return "拦下：越限断言（事实未越限却称超标）"
    if phrasing._adds_an_unsupported_judgement(template, cand, facts):
        return "拦下：凭空判断（模板未表态，改写表了态）"
    if phrasing._gives_advice(cand) and not phrasing._gives_advice(template):
        return "拦下：建议措辞"
    if not expanded and phrasing._is_padded(template, cand):
        return "拦下：长度上限"
    return "采纳"


def _recording_choose(template_text, model_text, facts, expanded=False):
    _trace.append({
        "template": template_text,
        "model": model_text,
        "expanded": expanded,
        "facts": phrasing.facts_brief(facts) if facts is not None else None,
        "verdict": _verdict(template_text, model_text, facts, expanded),
    })
    return _original_choose(template_text, model_text, facts, expanded=expanded)


def _robustness_questions() -> dict[str, list[str]]:
    rows = json.loads(
        (HERE / "噪声与引导实验结果_20260914_qwen3.5-4b.json").read_text(encoding="utf-8")
    )
    by_cat: dict[str, list[str]] = {}
    for r in rows:
        by_cat.setdefault(r["cat"], []).append(r["q"])
    return by_cat


def _run(temperature: float, questions: list[tuple[str, str]]) -> list[dict[str, object]]:
    runtime, runner = build_simulator_runtime()
    client = OllamaClient(temperature=temperature)
    if not client.probe():
        raise SystemExit(f"本地模型服务不可用：{client.last_error}")
    runtime.attach_language_model(client)

    poll_once = make_poll_once(runtime, runner)
    stop = threading.Event()

    def drive() -> None:
        runner.start()
        while not stop.is_set():
            poll_once()
            time.sleep(0.02)

    threading.Thread(target=drive, daemon=True).start()
    for _ in range(WARMUP_CYCLES):
        time.sleep(0.02)

    out: list[dict[str, object]] = []
    try:
        for label, question in questions:
            _trace.clear()
            started = time.monotonic()
            first = runtime.ask(question)
            final = first
            deadline = time.monotonic() + WAIT_SECONDS
            while time.monotonic() < deadline:
                later = runtime.poll_assistant()
                if later is not None:
                    final = later
                    break
                time.sleep(0.02)
            intent = final.intent
            row = {
                "label": label,
                "question": question,
                "intent": None if intent is None else intent.kind.value,
                "channel": None if intent is None else intent.channel,
                "first_text": first.text,
                "first_source": first.source.value,
                "final_text": final.text,
                "final_source": final.source.value,
                "applied": None if final.facts is None else final.facts.applied,
                "rephrase": list(_trace),
                "seconds": round(time.monotonic() - started, 1),
            }
            out.append(row)
            verdicts = "；".join(str(t["verdict"]) for t in _trace) or "未经改写"
            print(f"[{label}] {question}\n    → {final.text}\n    （{final.source.value}，{verdicts}）")
    finally:
        stop.set()
    return out


def main() -> None:
    phrasing.choose = _recording_choose
    cats = _robustness_questions()
    showcase = [
        ("取数", "现在温度多少"),
        ("解释档", "噪声超标了吗"),
        ("错误前提", cats["错误前提"][0]),
        ("错误前提", cats["错误前提"][2]),
        ("注入操纵", cats["注入操纵"][0]),
        ("注入操纵", cats["注入操纵"][4]),
        ("征询语气", cats["引导指令"][3]),
        ("指令", "把通风温度阈值调到 28 度"),
        ("复合句", "现在多少度啊，有点热，你可以帮我打开风扇嘛"),
        ("范围外", "今天股市怎么样"),
    ]
    readings = ["现在温度多少", "湿度现在是多少", "噪声多大", "温度平均多少",
                "湿度最低是多少", "噪声峰值多少", "屋里热吗", "吵不吵"]
    hot = [("高温改写", q) for _ in range(3) for q in readings]

    print("=== 第一组：现行配置（采样温度 0.3） ===")
    group1 = _run(0.3, showcase)
    print("\n=== 第二组：较高采样温度 0.8（表 5-16 的对照条件） ===")
    group2 = _run(0.8, hot)

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = HERE / f"约束展示实录_{stamp}_qwen3.5-4b.json"
    path.write_text(
        json.dumps({"录制时间": stamp, "数据源": "仿真模式",
                    "现行配置_温度0.3": group1, "对照_温度0.8": group2},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    blocked = [t for r in group2 for t in r["rephrase"] if str(t["verdict"]).startswith("拦下")]
    print(f"\n已保存：{path}\n0.8 下共 {sum(len(r['rephrase']) for r in group2)} 次改写，拦下 {len(blocked)} 次")


if __name__ == "__main__":
    main()
