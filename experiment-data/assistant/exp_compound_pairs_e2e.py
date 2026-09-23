"""复合句两两组合实验：端到端抽样（2026-09-15）。原在 scratchpad 编写，归档于此供复现，见同目录 README.md。

两两组合抽样，接真模型走 run_all 同款组合，测指令段复核的实际表现。

提问部分只走规则与模板，已由 exp_compound_pairs.py 全量覆盖；这里看的是模型会影响的那部分：
- 问+指令：复核是否同意（直接执行），还是冒出反问
- 问+问：有没有被错误执行成指令
"""

import random
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.automation_wiring import attach_language_model, make_poll_once  # noqa: E402
from scripts.run_gui import build_simulator_runtime  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from exp_compound_pairs import COMPOUND_KINDS, CONTROL, bank  # noqa: E402

WAIT = 25.0
SAMPLE_PER_GROUP = 25


def main() -> None:
    items = [r for r in bank() if r[2] in COMPOUND_KINDS | CONTROL and "，" not in r[0]]
    questions = [r for r in items if r[2] in COMPOUND_KINDS]
    instructions = [r for r in items if r[2] in CONTROL]
    rng = random.Random(20260915)
    qi = []
    while len(qi) < SAMPLE_PER_GROUP:
        a, b = rng.choice(questions), rng.choice(instructions)
        qi.append((a, b) if rng.random() < 0.5 else (b, a))
    qq = []
    while len(qq) < SAMPLE_PER_GROUP:
        a, b = rng.sample(questions, 2)
        if (a[2], a[3]) != (b[2], b[3]):
            qq.append((a, b))

    runtime, runner = build_simulator_runtime()
    available, detail = attach_language_model(runtime, enabled=True)
    print("模型：", available, detail)
    poll_once = make_poll_once(runtime, runner)
    stop = threading.Event()

    def drive() -> None:
        runner.start()
        while not stop.is_set():
            poll_once()
            time.sleep(0.02)

    threading.Thread(target=drive, daemon=True).start()
    time.sleep(2.0)

    results = {"问+指令": [], "问+问": []}
    try:
        for group, pairs in (("问+指令", qi), ("问+问", qq)):
            for a, b in pairs:
                runtime.assistant.reset_conversation()
                sentence = f"{a[0]}，{b[0]}"
                started = time.monotonic()
                first = runtime.ask(sentence)
                final = first
                if first.source.value == "pending":
                    deadline = time.monotonic() + WAIT
                    while time.monotonic() < deadline:
                        later = runtime.poll_assistant()
                        if later is not None:
                            final = later
                            break
                        time.sleep(0.02)
                seconds = time.monotonic() - started
                applied = final.facts is not None and final.facts.applied is True
                confirm = "是想让我" in final.text
                split = first.text != final.text or "。" in first.text
                results[group].append((sentence, applied, confirm, seconds, final.text))
                print(f"{group} {seconds:5.1f}s applied={applied!s:5} confirm={confirm!s:5} | {sentence} -> {final.text[:70]}")
                # 把风扇与阈值恢复成默认，免得上一句的设置影响下一句的回显
                if applied:
                    runtime.ask("风扇交给自动")
                    for _ in range(300):
                        if runtime.poll_assistant() is not None:
                            break
                        time.sleep(0.02)
                    runtime.assistant.reset_conversation()
    finally:
        stop.set()

    qi_rows = results["问+指令"]
    qq_rows = results["问+问"]
    print("\n问+指令", len(qi_rows), "句：直接执行", sum(r[1] for r in qi_rows),
          "反问", sum(r[2] for r in qi_rows), "中位耗时",
          f"{sorted(r[3] for r in qi_rows)[len(qi_rows) // 2]:.1f}s")
    print("问+问", len(qq_rows), "句：错误执行", sum(r[1] for r in qq_rows),
          "反问", sum(r[2] for r in qq_rows))
    unexpected = [r for r in qi_rows if not r[1]]
    for r in unexpected:
        print("  未执行：", r[0], "->", r[4])


if __name__ == "__main__":
    main()
