"""把"一句回答是怎么来的"逐步录下来，供网页控制台离线回放（2026-09-26）。

网页的问答页会按时间逐步点亮一句回答的来路（`docs/decisions/08-web.md`）。
在线时这些步骤由网关实时推送；演示现场可能没有模型、没有网络，所以用本脚本
提前走一遍正式装配，把每题的步骤连同原始耗时录下来，由 `scripts/build_web_replay.py`
并进 `web/replay/replay-data.js`，回放时按原始节奏重演。

装配与 `run_api_server.py` 相同：仿真运行时 + `OllamaClient` + `make_poll_once`，
步骤走的正是网关用的 `on_assistant_steps` 出口，并用网关自己的序列化函数
（`gateway.events.assistant_step_message`）存成消息——回放看到的与在线时逐字段一致。

**不改 `src/` 一行**，也不改变任何判定：只是把步骤日志取出来存盘。

分两组：

1. **现行配置**（采样温度 0.3）：每条路径各一题——取数、解释档、规则落空交给模型分类、
   指令复核一致、规则读成指令而模型不同意（随后回答"不用了"）、越界数值、复合句、
   错误前提、范围外。
2. **采样温度 0.8**（与约束展示实录相同的对照条件）：读数类问题反复问，只留下出口检查
   **真的拦下**过的几题。现行配置下出口检查零触发，"被拦 → 重试"只在这个条件下录得到，
   与 `exp_constraint_showcase.py` 同一做法，页面上注明。

数据源是仿真模式，读数不是现场值；要展示的是流程，不是读数本身。

用法::

    python experiment-data/assistant/exp_assistant_steps.py
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent  # experiment-data/assistant -> 仓库根
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from gateway.events import answer_detail, assistant_step_message  # noqa: E402
from llm.ollama import OllamaClient  # noqa: E402
from scripts.automation_wiring import make_poll_once  # noqa: E402
from scripts.run_gui import build_simulator_runtime  # noqa: E402
from service.assistant.models import Answer, AnswerStep  # noqa: E402

WAIT_SECONDS = 45.0
WARMUP_CYCLES = 150
HOT_TRIES = 24
HOT_KEEP = 3

CURRENT = [
    ("取数", "现在温度多少"),
    ("解释档", "噪声超标了吗"),
    ("规则落空，交给模型分类", "站台暖和吗"),
    ("指令：复核一致", "帮我把风扇打开"),
    ("指令：规则与模型不一致", "我没让你开风扇"),
    ("回答确认问句", "不用了"),
    ("越界数值", "通风温度阈值调到1000度"),
    ("复合句", "现在多少度啊，有点热，你可以帮我打开风扇嘛"),
    ("错误前提", "温度都40度了吧"),
    ("范围外", "今天股市怎么样"),
]
READINGS = ["现在温度多少", "湿度现在是多少", "噪声多大", "屋里热吗", "吵不吵", "温度平均多少"]


def _answer_payload(answer: Answer) -> dict[str, Any]:
    """与 POST /assistant/ask 返回体相同的形状。"""
    return {"text": answer.text, "source": answer.source.value, **answer_detail(answer)}


class _Recorder:
    """Collects steps from the poll loop's sink, keyed by question."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.steps: dict[int, list[dict[str, Any]]] = {}
        self.details: dict[int, dict[str, Any]] = {}

    def on_steps(self, steps: tuple[AnswerStep, ...]) -> None:
        with self._lock:
            for step in steps:
                self.steps.setdefault(step.question_id, []).append(
                    assistant_step_message(step)
                )

    def on_detail(self, answer: Answer) -> None:
        with self._lock:
            self.details[answer.question_id] = _answer_payload(answer)

    def finished(self, qid: int) -> bool:
        with self._lock:
            return any(
                s["kind"] == "answered" and s["final"] for s in self.steps.get(qid, [])
            )


def _run(temperature: float, questions: list[tuple[str, str]]) -> list[dict[str, Any]]:
    runtime, runner = build_simulator_runtime()
    client = OllamaClient(temperature=temperature)
    if not client.probe():
        raise SystemExit(f"本地模型服务不可用：{client.last_error}")
    runtime.attach_language_model(client)

    recorder = _Recorder()
    poll_once = make_poll_once(
        runtime,
        runner,
        on_assistant_detail=recorder.on_detail,
        on_assistant_steps=recorder.on_steps,
    )
    stop = threading.Event()

    def drive() -> None:
        runner.start()
        while not stop.is_set():
            poll_once()
            time.sleep(0.02)

    threading.Thread(target=drive, daemon=True).start()
    for _ in range(WARMUP_CYCLES):
        time.sleep(0.02)

    out: list[dict[str, Any]] = []
    try:
        for label, question in questions:
            first = runtime.ask(question)
            qid = first.question_id
            deadline = time.monotonic() + WAIT_SECONDS
            while time.monotonic() < deadline and not recorder.finished(qid):
                time.sleep(0.05)
            time.sleep(0.2)  # let the last drain land
            steps = [dict(s, question_id=0) for s in recorder.steps.get(qid, [])]
            final = recorder.details.get(qid) or _answer_payload(first)
            row = {
                "label": label,
                "question": question,
                "first": _answer_payload(first),
                "final": final,
                "steps": steps,
                "complete": recorder.finished(qid),
            }
            out.append(row)
            took = steps[-1]["at_ms"] / 1000 if steps else 0
            checks = [s["verdict"] for s in steps if s["kind"] == "checks"]
            print(f"[{label}] {question}\n    → {final['text']}\n"
                  f"    （{final['source']}，{len(steps)} 步，{took:.1f} s，检查 {checks or '无'}）")
    finally:
        stop.set()
    return out


def _was_refused(row: dict[str, Any]) -> bool:
    return any(
        s["kind"] == "checks" and s["verdict"] != "accepted" for s in row["steps"]
    )


def main() -> None:
    print("=== 第一组：现行配置（采样温度 0.3） ===")
    group1 = _run(0.3, CURRENT)
    print("\n=== 第二组：采样温度 0.8，只留被拦下过的 ===")
    tries = [("高温改写", READINGS[i % len(READINGS)]) for i in range(HOT_TRIES)]
    hot = _run(0.8, tries)
    refused = [r for r in hot if _was_refused(r)]
    # 不同问题各留一题，尽量覆盖不同的拦截原因
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in refused:
        verdicts = {s["verdict"] for s in row["steps"] if s["kind"] == "checks"}
        key = row["question"]
        if key in seen:
            continue
        if kept and verdicts <= {v for k in kept for s in k["steps"] if s["kind"] == "checks" for v in [s["verdict"]]}:
            continue
        kept.append(row)
        seen.add(key)
        if len(kept) >= HOT_KEEP:
            break
    if len(kept) < HOT_KEEP:
        for row in refused:
            if row not in kept and row["question"] not in seen:
                kept.append(row)
                seen.add(row["question"])
            if len(kept) >= HOT_KEEP:
                break

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = HERE / f"实时流程录制_{stamp}_qwen3.5-4b.json"
    path.write_text(
        json.dumps(
            {
                "录制时间": stamp,
                "数据源": "仿真模式",
                "说明": "每题的步骤即网关推送的 assistant_step 消息，question_id 置 0，at_ms 为距提问的原始毫秒数。",
                "现行配置_温度0.3": group1,
                "对照_温度0.8": kept,
                "对照_温度0.8_总尝试": len(hot),
                "对照_温度0.8_被拦题数": len(refused),
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\n已保存：{path}\n0.8 下 {len(hot)} 题里 {len(refused)} 题被拦过，留 {len(kept)} 题")


if __name__ == "__main__":
    main()
