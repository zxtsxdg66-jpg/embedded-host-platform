"""复合句两两组合实验：规则层全量（2026-09-15）。原在 scratchpad 编写，归档于此供复现，见同目录 README.md。

两两组合题库，只测规则层的拆句（不接模型）。

复合句的提问部分只走规则 + 模板，模型不参与，所以规则层能完整回答
"拆句认没认对"。模型只影响指令段的复核，那部分由 exp_compound_pairs_e2e.py 抽样测。
"""

import itertools
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r"D:\毕业设计")
sys.path.insert(0, str(ROOT / "src"))

from device.sensors.channels import HUMIDITY_CHANNEL, NOISE_CHANNEL, TEMPERATURE_CHANNEL  # noqa: E402
from service.assistant import intent as rules  # noqa: E402
from service.assistant.assistant import Assistant  # noqa: E402
from service.data_models import DataPoint  # noqa: E402
from service.sensor_data_processor import SensorDataProcessor  # noqa: E402
from service.ventilation_controller import VentilationController  # noqa: E402

OUT = Path(__file__).resolve().parent
COMPOUND_KINDS = {"current_value", "minimum", "maximum", "average", "alarm_state",
                  "threshold_info", "fan_state", "device_list"}
CONTROL = {"fan_on", "fan_off", "fan_auto", "set_vent_threshold"}


def bank() -> list[tuple[str, str, str | None, str | None]]:
    src = (ROOT / "scripts/assistant_benchmark.py").read_text(encoding="utf-8")
    rows = re.findall(
        r'^\s*\("([^"]+)",\s*(QUESTION|INSTRUCTION|OUT_OF_SCOPE),\s*(None|"[^"]*"),\s*(None|"[^"]*"),?\s*\)',
        src, re.M)
    unq = lambda s: None if s == "None" else s.strip('"')  # noqa: E731
    return [(q, k, unq(i), unq(c)) for q, k, i, c in rows]


def fresh() -> tuple[Assistant, VentilationController]:
    processor = SensorDataProcessor()
    for channel, value in ((TEMPERATURE_CHANNEL, 26.5), (HUMIDITY_CHANNEL, 62.0), (NOISE_CHANNEL, 55.0)):
        processor.handle_data_point(DataPoint(device_id="dev-1", channel=channel, value=value))
    ventilation = VentilationController()
    return Assistant(processor, lambda: ["dev-1"], ventilation=ventilation, clock_ms=lambda: 1_000_000), ventilation


def single_ok(q: str, kind: str, want: str | None, channel: str | None) -> bool:
    assistant, _ = fresh()
    answer = assistant.ask(q)
    got = None if answer.intent is None else answer.intent.kind.value
    got_ch = None if answer.intent is None else answer.intent.channel
    applied = None if answer.facts is None else answer.facts.applied
    if kind == "INSTRUCTION":
        return got == want and applied is True and (channel is None or got_ch == channel)
    return got == want and (channel is None or got_ch == channel)


def main() -> None:
    items = [row for row in bank()
             if row[2] in COMPOUND_KINDS | CONTROL and "，" not in row[0]]
    single = {row[0]: single_ok(*row) for row in items}
    print(f"参与组合的单句 {len(items)} 条，规则单独判对 {sum(single.values())} 条")

    stats: Counter[str] = Counter()
    failures: list[dict] = []
    for (qa, ka, ia, ca), (qb, kb, ib, cb) in itertools.permutations(items, 2):
        if ia in CONTROL and ib in CONTROL:
            continue  # 两条指令按设计不拆
        if (ia, ca) == (ib, cb):
            continue  # 同一个问题问两遍按设计合并
        group = "问+指令" if (ia in CONTROL or ib in CONTROL) else "问+问"
        sentence = f"{qa}，{qb}"
        assistant, ventilation = fresh()
        split = assistant._split_compound(sentence)
        expected = {(ia, ca), (ib, cb)}
        if split is None:
            got = set()
        else:
            questions, instruction = split
            got = {(q.kind.value, q.channel) for q in questions}
            if instruction is not None:
                got.add((instruction[0].kind.value, instruction[0].channel))
        # 期望通道为 None 的项不约束通道
        def matches(exp, got=got):
            return all(any(g[0] == e[0] and (e[1] is None or g[1] == e[1]) for g in got) for e in exp) and len(got) == len(exp)
        ok = matches(expected)
        applied_ok = True
        if ok and group == "问+指令":
            answer = assistant.ask(sentence)
            applied_ok = answer.facts is not None and answer.facts.applied is True
        both_single = single[qa] and single[qb]
        stats[f"{group}|全部"] += 1
        stats[f"{group}|拆对"] += ok and applied_ok
        stats[f"{group}|单句都对"] += both_single
        stats[f"{group}|单句都对且拆对"] += both_single and ok and applied_ok
        if both_single and not (ok and applied_ok):
            failures.append({"sentence": sentence, "expected": sorted(map(str, expected)),
                             "got": sorted(map(str, got)), "applied_ok": applied_ok})

    for group in ("问+问", "问+指令"):
        total = stats[f"{group}|全部"]
        both = stats[f"{group}|单句都对"]
        print(f"\n{group}：组合 {total} 句")
        print(f"  拆句认对两件事：{stats[f'{group}|拆对']}/{total} = {stats[f'{group}|拆对'] / total:.1%}")
        print(f"  两句单独问都对：{both}/{total} = {both / total:.1%}（'效果差不多'的对照）")
        print(f"  单句都对的组合里拆对：{stats[f'{group}|单句都对且拆对']}/{both} = {stats[f'{group}|单句都对且拆对'] / both:.1%}")

    # 失败按"哪一句拖后腿"归因：统计每个单句在失败组合里出现的次数
    culprit: Counter[str] = Counter()
    for f in failures:
        for part in f["sentence"].split("，"):
            culprit[part] += 1
    print(f"\n单句都对却拆错的组合 {len(failures)} 句，出现最多的单句：")
    for q, n in culprit.most_common(20):
        print(f"  {n:4d}  {q}")
    (OUT / "compound_pairs_failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
