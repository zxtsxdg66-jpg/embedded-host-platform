"""Measure how well the assistant understands questions, on a fixed question bank.

Purpose
-------
``demo_rehearsal.py`` answers "will the demo work today"; this one answers
"how often is the assistant right, and where does it go wrong". It types 65
questions at the same composition ``run_all_界面加网关.bat`` uses -- the simulator
runtime, ``attach_language_model()``, the same ``poll_once()`` -- and grades
every answer against an expected intent.

Three numbers come out of it, and they must be read separately:

- **规则命中率**: how many questions never needed the model at all. This is
  the one worth raising, because a rule hit is instant and identical every
  time. A model call is neither.
- **模型分类成功率**: of the questions the rules missed, how many the model
  classified correctly.
- **改写采纳率**: how many model rewordings survived the grounding check.
  Rejections here are the check doing its job, not a defect.

Why it exists
-------------
Its first run turned up eight failures, and five of them were **missing
keywords in the rules**, not model errors -- "最干的时候湿度多少" was read as
a request for the current value because the MINIMUM list knew 最低 but not
最干. Adding the eight words lifted the rule hit rate from 69% to 78% and the
overall score from 88% to 92%, which no amount of prompt tuning would have
done. The lesson is worth keeping in front of whoever reads this next:
**when an answer is wrong, check the keyword lists before touching the
prompt.**

Exit code is 1 if an **instruction** or an **out-of-scope** question was
graded wrong. Those are the categories where being wrong has consequences:
an instruction has side effects, and answering something outside the
system's scope means it invented a topic. A missed *question* is reported
but tolerated -- the user simply rephrases.

Usage::

    python scripts/assistant_benchmark.py              # 接模型，约 7 分钟
    python scripts/assistant_benchmark.py --no-llm     # 只测规则，数秒
    python scripts/assistant_benchmark.py --wait 10
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from application.runtime import ApplicationRuntime  # noqa: E402
from scripts.automation_wiring import (  # noqa: E402
    attach_language_model,
    make_poll_once,
)
from scripts.run_gui import build_simulator_runtime  # noqa: E402
from service.assistant.models import Answer  # noqa: E402

QUESTION = "问"
INSTRUCTION = "指令"
OUT_OF_SCOPE = "范围外"

# (问句, 类别, 期望意图, 期望通道)。期望意图为 None 表示"应当被拒绝"。
BANK: tuple[tuple[str, str, str | None, str | None], ...] = (
    # 当前值：书面与口语混排
    ("现在温度多少", QUESTION, "current_value", "temperature"),
    ("湿度现在是多少", QUESTION, "current_value", "humidity"),
    ("噪声多大", QUESTION, "current_value", "noise"),
    ("外面冷不冷", QUESTION, "current_value", "temperature"),
    ("屋里热吗", QUESTION, "current_value", "temperature"),
    ("现在几度", QUESTION, "current_value", "temperature"),
    ("空气干不干", QUESTION, "current_value", "humidity"),
    ("潮不潮", QUESTION, "current_value", "humidity"),
    # 2026-09-09 真人试用：错别字与裸的体感词，规则当时全部落空。
    ("现在多少读", QUESTION, "current_value", "temperature"),
    ("燥音多少", QUESTION, "current_value", "noise"),
    ("有点热呢", QUESTION, "current_value", "temperature"),
    ("好闷啊", QUESTION, "current_value", "humidity"),
    ("吵不吵", QUESTION, "current_value", "noise"),
    ("这会儿安静吗", QUESTION, "current_value", "noise"),
    ("温度怎么样了", QUESTION, "current_value", "temperature"),
    ("湿度情况如何", QUESTION, "current_value", "humidity"),
    # 最值
    ("温度最高多少", QUESTION, "maximum", "temperature"),
    ("湿度最低是多少", QUESTION, "minimum", "humidity"),
    ("噪声峰值多少", QUESTION, "maximum", "noise"),
    ("这一阵子最吵到多少", QUESTION, "maximum", "noise"),
    ("今天最热的时候多少度", QUESTION, "maximum", "temperature"),
    ("最干的时候湿度多少", QUESTION, "minimum", "humidity"),
    ("温度到过的最低点是多少", QUESTION, "minimum", "temperature"),
    ("最闹腾的时候有多响", QUESTION, "maximum", "noise"),
    # 平均
    ("温度平均多少", QUESTION, "average", "temperature"),
    ("噪声的平均值是多少", QUESTION, "average", "noise"),
    ("这一阵子平均多少度", QUESTION, "average", "temperature"),
    ("平时湿度大概在什么水平", QUESTION, "average", "humidity"),
    # 是否超标
    ("噪声超标了吗", QUESTION, "alarm_state", "noise"),
    ("温度超了没有", QUESTION, "alarm_state", "temperature"),
    ("湿度正常吗", QUESTION, "alarm_state", "humidity"),
    ("站里是不是太热了", QUESTION, "alarm_state", "temperature"),
    ("声音是不是太大了", QUESTION, "alarm_state", "noise"),
    ("湿度有没有报警", QUESTION, "alarm_state", "humidity"),
    # 阈值
    ("噪声的报警阈值是多少", QUESTION, "threshold_info", "noise"),
    ("温度阈值设的多少", QUESTION, "threshold_info", "temperature"),
    ("多大声算超标", QUESTION, "threshold_info", "noise"),
    ("湿度低于多少会报警", QUESTION, "threshold_info", "humidity"),
    # 2026-09-09：错别字与裸的体感词，取自真人试用。
    # "阀值"不是手滑而是流传很广的误写，打字时理直气壮。
    ("阀值是多少", QUESTION, "threshold_info", None),
    ("噪声阀值多少", QUESTION, "threshold_info", "noise"),
    # 余量按需：问了才附带，"现在多少度"不再硬塞。
    ("现在温度多少，还差多少超限", QUESTION, "current_value", "temperature"),
    ("温度快超了吗", QUESTION, "current_value", "temperature"),
    # 手动播报：认出但拒绝。
    ("测试一下报警发声", QUESTION, "announce_request", None),
    ("试一下语音播报能不能响", QUESTION, "announce_request", None),
    # 风扇与设备
    ("风扇在转吗", QUESTION, "fan_state", None),
    ("风扇为什么在转", QUESTION, "fan_state", None),
    ("那个吹风的开着没", QUESTION, "fan_state", None),
    # 词表放宽到裸的"开"之后，这几句必须仍然读作提问而非命令。
    ("风扇开着吗", QUESTION, "fan_state", None),
    ("风扇开了没", QUESTION, "fan_state", None),
    ("风扇是自动的吗", QUESTION, "fan_state", None),
    ("通风现在什么状态", QUESTION, "fan_state", None),
    ("有几个设备在线", QUESTION, "device_list", None),
    ("现在连了几台机器", QUESTION, "device_list", None),
    ("设备都连上了吗", QUESTION, "device_list", None),
    # 指令：开
    ("把风扇打开", INSTRUCTION, "fan_on", None),
    ("开一下风扇", INSTRUCTION, "fan_on", None),
    ("让风扇转起来", INSTRUCTION, "fan_on", None),
    ("太热了让那个吹风的转起来", INSTRUCTION, "fan_on", None),
    ("通风开起来", INSTRUCTION, "fan_on", None),
    # 2026-09-09 真人试用中说出、当时规则全部认不出的五种说法。
    # 原有的四条例句每一条都恰好含有词表里已有的词，题库与词表互为印证，
    # 因此测不出"开"这个最短说法根本不在表里。
    ("开风扇", INSTRUCTION, "fan_on", None),
    ("能开风扇不", INSTRUCTION, "fan_on", None),
    ("把风扇开了", INSTRUCTION, "fan_on", None),
    ("帮我开风扇", INSTRUCTION, "fan_on", None),
    ("可以开风扇吗", INSTRUCTION, "fan_on", None),
    # 指令：关
    ("关掉风扇", INSTRUCTION, "fan_off", None),
    ("把风扇停了", INSTRUCTION, "fan_off", None),
    ("别吹了关上吧", INSTRUCTION, "fan_off", None),
    ("风扇关闭", INSTRUCTION, "fan_off", None),
    # 2026-09-09 新增的四类，均来自真人试用或事故复盘。
    # 裸开关：反问而不猜（"那你开开呗"没提风扇）。
    ("那你开开呗", QUESTION, "bare_switch", None),
    ("打开", QUESTION, "bare_switch", None),
    ("关了吧", QUESTION, "bare_switch", None),
    ("别开风扇", INSTRUCTION, "fan_off", None),
    # 指令：交回自动
    ("风扇交给自动", INSTRUCTION, "fan_auto", None),
    ("风扇改成自动模式", INSTRUCTION, "fan_auto", None),
    ("让通风自动控制", INSTRUCTION, "fan_auto", None),
    # 指令：改阈值
    ("把通风温度阈值调到 28 度", INSTRUCTION, "set_vent_threshold", "temperature"),
    ("通风湿度阈值设成 75", INSTRUCTION, "set_vent_threshold", "humidity"),
    ("通风阈值调到 26 度", INSTRUCTION, "set_vent_threshold", "temperature"),
    ("把通风温度阈值改成 31", INSTRUCTION, "set_vent_threshold", "temperature"),
    # 应当被拒绝的
    ("今天股市怎么样", OUT_OF_SCOPE, None, None),
    ("你叫什么名字", OUT_OF_SCOPE, None, None),
    ("帮我订张票", OUT_OF_SCOPE, None, None),
    ("明天会下雨吗", OUT_OF_SCOPE, None, None),
    ("给我讲个笑话", OUT_OF_SCOPE, None, None),
    ("北京到上海多远", OUT_OF_SCOPE, None, None),
    ("地铁几点收班", OUT_OF_SCOPE, None, None),
    ("你是什么模型", OUT_OF_SCOPE, None, None),
)
"""题库。四类刻意按真实使用比例配：问句最多，指令次之，范围外八条。

范围外那一组不能省——只测顺利路径的评测，发现不了一个"对什么都说好"的系统；
而问句里书面与口语各占一半，因为规则词表天然覆盖书面语，只测书面语会把成功率
测得虚高。
"""

DEFAULT_WAIT_SECONDS = 20.0
"""等模型结果的上限，与 ``OllamaClient`` 自身的超时对齐。

规则命中的问句也会等一次改写（用于统计采纳率），落空的等分类结果；
两者都在结果到达时立刻继续，因此这个值只在模型确实不产出时才被耗满。
"""

_WARMUP_CYCLES = 100
"""开跑前先转几圈，让统计量里有样本——否则"最高值"一类问题会答"还没有有效读数"。"""


def _grade(
    kind: str,
    want_intent: str | None,
    want_channel: str | None,
    answer: Answer,
) -> bool:
    """这条回答算不算对。"""
    got_intent = None if answer.intent is None else answer.intent.kind.value
    got_channel = None if answer.intent is None else answer.intent.channel
    applied = None if answer.facts is None else answer.facts.applied

    if want_intent is None:
        # 范围外：回落到帮助文案才算对。答出任何具体内容都意味着它编了个话题。
        return got_intent in (None, "help")
    if kind == INSTRUCTION:
        # 指令还要求真的执行了：认出来却没落到设置上，等于没做。
        return (
            got_intent == want_intent
            and applied is True
            and (want_channel is None or got_channel == want_channel)
        )
    return got_intent == want_intent and (
        want_channel is None or got_channel == want_channel
    )


def run(wait: float, enabled: bool) -> list[dict[str, object]]:
    runtime, runner = build_simulator_runtime()
    available, detail = attach_language_model(runtime, enabled=enabled)
    state = "已接入" if available else "未接入"
    print(f"模型：{state}{' — ' + detail if detail else ''}\n")

    poll_once = make_poll_once(runtime, runner)
    stop = threading.Event()

    def drive() -> None:
        runner.start()
        while not stop.is_set():
            poll_once()
            time.sleep(0.02)

    threading.Thread(target=drive, daemon=True, name="bench-driver").start()
    for _ in range(_WARMUP_CYCLES):
        time.sleep(0.02)

    rows: list[dict[str, object]] = []
    try:
        for question, kind, want_intent, want_channel in BANK:
            started = time.monotonic()
            first = runtime.ask(question)
            # 不接模型时不必等：即时答案就是最终答案。
            final = (
                _ask_and_wait_existing(runtime, first, wait) if available else first
            )
            ok = _grade(kind, want_intent, want_channel, final)
            got = None if final.intent is None else final.intent.kind.value
            channel = None if final.intent is None else final.intent.channel
            rows.append({
                "question": question,
                "kind": kind,
                "want": want_intent,
                "want_channel": want_channel,
                "first": first.source.value,
                "final": final.source.value,
                "got": got,
                "got_channel": channel,
                "ok": ok,
                "applied": None if final.facts is None else final.facts.applied,
                "seconds": time.monotonic() - started,
            })
            print(
                f"{'OK' if ok else 'NG'} {rows[-1]['seconds']:5.1f}s "
                f"[{first.source.value:>12s}→{final.source.value:<12s}] "
                f"{question:24s} 期望 {want_intent}/{want_channel} "
                f"得到 {got}/{channel}"
            )
    finally:
        stop.set()

    llm = runtime.assistant.llm
    rows.append({
        "counters": {
            "请求数": getattr(llm, "request_count", 0),
            "超时数": getattr(llm, "timeout_count", 0),
            "失败数": getattr(llm, "failure_count", 0),
        }
    })
    return rows


def _ask_and_wait_existing(
    runtime: ApplicationRuntime, first: Answer, wait: float
) -> Answer:
    """等这次提问的模型结果。提问已经发生，这里只负责轮询。"""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        later = runtime.poll_assistant()
        if later is not None:
            return later
        time.sleep(0.02)
    return first


def report(rows: list[dict[str, object]], model_attached: bool = True) -> int:
    counters = next((r["counters"] for r in rows if "counters" in r), {})
    graded = [r for r in rows if "ok" in r]
    total = len(graded)
    ok = sum(bool(r["ok"]) for r in graded)

    print("\n" + "=" * 78)
    print(f"总体：{ok}/{total} = {ok / total:.1%}\n")

    print("按类别：")
    failed_critical = False
    for kind in (QUESTION, INSTRUCTION, OUT_OF_SCOPE):
        sub = [r for r in graded if r["kind"] == kind]
        hit = sum(bool(r["ok"]) for r in sub)
        print(f"  {kind:4s} {hit:2d}/{len(sub):2d} = {hit / len(sub):6.1%}")
        if hit < len(sub) and kind in (INSTRUCTION, OUT_OF_SCOPE):
            failed_critical = True

    rule_hit = [r for r in graded if r["first"] != "fallback"]
    rule_miss = [r for r in graded if r["first"] == "fallback"]
    print(f"\n规则命中：{len(rule_hit)}/{total} = {len(rule_hit) / total:.1%}"
          "（这些问句不需要模型，零延迟且每次一致）")

    need_model = [r for r in rule_miss if r["want"] is not None]
    if need_model:
        hit = sum(bool(r["ok"]) for r in need_model)
        print(f"模型分类：真正需要模型的 {len(need_model)} 条里判对 {hit} 条 = "
              f"{hit / len(need_model):.1%}")

    rephrased = [r for r in rule_hit if r["final"] == "model"]
    if rule_hit:
        print(f"改写采纳：{len(rephrased)}/{len(rule_hit)} = "
              f"{len(rephrased) / len(rule_hit):.1%}"
              "（其余退回模板：超时，或数字未过接地校验）")

    # 2026-09-14 起指令要先过模型复核：两边一致才执行，不一致就反问。
    # 因此"没执行"分两种，代价完全不同——被反问拦下的那一条设备状态没变，
    # 用户回一句"是"就能继续；真正错执行的那一条已经动了设置。
    held = [
        r
        for r in graded
        if r["kind"] == INSTRUCTION and not r["ok"] and r["got"] == r["want"]
    ]
    wrongly_acted = [
        r
        for r in graded
        if r["kind"] != INSTRUCTION and r["applied"] is True
    ]
    if held or wrongly_acted:
        print(f"\n复核拦下（意图判对但等确认）：{len(held)}")
        print(f"错误执行（不该动设置却动了）：{len(wrongly_acted)}")

    bad = [r for r in graded if not r["ok"]]
    if bad:
        print(f"\n未通过的 {len(bad)} 条：")
        for r in bad:
            print(f"  {r['kind']:4s} {str(r['question']):24s} "
                  f"期望 {r['want']}/{r['want_channel']} "
                  f"得到 {r['got']}/{r['got_channel']} [{r['final']}]")
        print("\n  先查规则词表再改提示词：多数错答是关键词缺失，"
              "补一个词能把这句话变成零延迟且恒定的规则命中。")

    seconds = sorted(float(r["seconds"]) for r in graded)  # type: ignore[arg-type]
    print(f"\n耗时：中位 {seconds[len(seconds) // 2]:.1f}s，最长 {seconds[-1]:.1f}s")
    print("来源分布：", dict(Counter(str(r["final"]) for r in graded)))
    if counters:
        print("模型客户端计数：", counters)

    if not model_attached:
        print()
        print('本次未接模型：口语说法本就该落到帮助文案，因此不据此判定失败。')
        print('这一趟量的是规则覆盖率——它是唯一零延迟且每次一致的部分。')
        return 0

    if failed_critical:
        print("\n指令类或范围外出现错答——这两类错了是有后果的，需要处理。")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="问答成功率评测")
    parser.add_argument(
        "--wait",
        type=float,
        default=DEFAULT_WAIT_SECONDS,
        help=f"等模型结果的秒数（默认 {DEFAULT_WAIT_SECONDS:g}）",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="不接模型，只测规则覆盖（秒级完成）",
    )
    args = parser.parse_args(argv)

    rows = run(wait=args.wait, enabled=not args.no_llm)
    return report(rows, model_attached=not args.no_llm)


if __name__ == "__main__":
    raise SystemExit(main())
