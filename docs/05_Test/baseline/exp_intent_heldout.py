"""意图识别泛化实验（2026-09-14）。原在 scratchpad 编写，归档于此供复现，见同目录 README.md"留出题库"一节。

实验 1：留出题库只跑规则（service.assistant.intent.recognise）。
实验 2：同一题库绕过规则直接问模型：
    A = 现行做法：PARSE_SYSTEM_PROMPT + 自由文本 + parsing.parse_reply
    B = 同一提示词 + Ollama format（JSON Schema，标签与通道均为枚举）
组合：规则返回 HELP 时才用模型结果（与线上管线一致）。

题库由 hassil 风格模板展开：(a|b) 多选一，[x] 可选；固定种子抽样，剔除基准题库原句。
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"D:\毕业设计")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.assistant_benchmark import BANK  # noqa: E402
from service.assistant import parsing  # noqa: E402
from service.assistant.intent import recognise  # noqa: E402
from service.assistant.models import IntentKind  # noqa: E402

OUT = Path(__file__).resolve().parent
T, H, N = "temperature", "humidity", "noise"
UNKNOWN = "unknown"

# (期望标签, 期望通道, 模板列表)
TEMPLATES: list[tuple[str, str | None, list[str]]] = [
    ("current_value", T, [
        "(站厅|站台|这边)[现在](冷不冷|热不热|暖和吗|凉快吗)",
        "[现在](气温|温度)(几度|多高|咋样)",
        "报一下(当前|实时)(气温|温度)",
    ]),
    ("current_value", H, [
        "(站台|这边)[现在](湿不湿|干燥吗|潮湿吗)",
        "(空气|这里的)湿度(咋样|多少了)",
        "现在的相对湿度(是多少|多大)",
    ]),
    ("current_value", N, [
        "(站台|站厅)[现在](吵吗|闹不闹|安静不安静)",
        "(当前|实时)(噪音|分贝)(多少|报一下)",
        "这会儿有多少分贝",
    ]),
    ("maximum", T, ["(今天|开机以来)(温度|气温)最高(到过|是)多少", "最热那会儿多少度"]),
    ("maximum", H, ["湿度(最高|最大)(到过|是)多少", "最潮的时候湿度多少"]),
    ("maximum", N, ["(最响|最吵)的时候(多少分贝|有多大声)", "噪音(最大|最高)值是多少"]),
    ("minimum", T, ["(最冷|最凉快)的时候多少度", "气温(最低|最小)(到过|是)多少"]),
    ("minimum", H, ["湿度(最低|最小)值是多少", "最干燥那会儿湿度多少"]),
    ("minimum", N, ["(最安静|最静)的时候多少分贝", "噪音(最低|最小)(是|到过)多少"]),
    ("average", T, ["(温度|气温)(平均|均值)(是|有)多少", "整体来看平均多少度"]),
    ("average", H, ["湿度(一般|通常|平均)在多少", "湿度均值(多少|是多少)"]),
    ("average", N, ["噪音平均(多少分贝|水平怎样)", "分贝均值是多少"]),
    ("alarm_state", T, ["(温度|气温)(超标|越限)了(吗|没)", "站里(热得|温度)(超限没|有没有超标)"]),
    ("alarm_state", H, ["湿度(是不是|有没有)(超出范围|不正常)", "湿度(报警|超限)了没"]),
    ("alarm_state", N, ["(噪音|分贝)(超没超标|有没有超限)", "站台吵得(超标了吗|超限了吗)"]),
    ("threshold_info", T, ["温度(报警线|上限)是多少", "气温到多少度算超标"]),
    ("threshold_info", H, ["湿度(报警线|正常范围)是多少", "湿度多少算不正常"]),
    ("threshold_info", N, ["噪音(报警线|上限|标准)是多少", "超过多少分贝算超标"]),
    ("fan_state", None, ["(风扇|排风机)[现在](开着吗|在工作吗|什么状态)", "为啥(风扇|排风)(一直在转|开了)"]),
    ("device_list", None, ["(现在|目前)(有几台|多少个)(设备|传感器)(在线|连着)", "采集板连上了没"]),
    ("fan_on", None, ["(帮忙|麻烦)把(风扇|排风)(开开|打开|启动)", "(有点闷|太热了)开下(风扇|通风)", "启动排风"]),
    ("fan_off", None, ["(风扇|排风)(停一下|关了吧|先关掉)", "别让风扇转了", "把通风停掉"]),
    ("fan_auto", None, ["(风扇|通风)(设成|改为|切到)自动", "风扇让系统自己决定开关"]),
    ("set_vent_threshold", T, ["(通风|排风)温度(阈值|触发线)(改为|设到|调成)(27|29|32)度"]),
    ("set_vent_threshold", H, ["(通风|排风)湿度(阈值|触发线)(改为|调成)(70|72|78)"]),
    (UNKNOWN, None, [
        "(今天|明天)天气怎么样", "帮我(打个车|点个外卖)", "(推荐|介绍)一首歌",
        "你(是谁|几岁了)", "下一班车几点到", "附近有厕所吗",
        "空调温度调到 26 度", "手机噪音太大怎么办", "明天温度多少",
        "帮我查一下湿疹怎么治", "站台的广播声音能调小吗",
    ]),
]
PER_GROUP = 6
PER_GROUP_UNKNOWN = 14
SEED = 20260914

_TOKEN = re.compile(r"\(([^()]*)\)|\[([^\[\]]*)\]")


def expand(template: str) -> list[str]:
    parts: list[list[str]] = []
    pos = 0
    for m in _TOKEN.finditer(template):
        if m.start() > pos:
            parts.append([template[pos:m.start()]])
        if m.group(1) is not None:
            parts.append(m.group(1).split("|"))
        else:
            parts.append(["", m.group(2)])
        pos = m.end()
    if pos < len(template):
        parts.append([template[pos:]])
    return ["".join(p) for p in itertools.product(*parts)]


def build_set() -> list[dict[str, object]]:
    rng = random.Random(SEED)
    seen_bank = {q for q, *_ in BANK}
    rows: list[dict[str, object]] = []
    for label, channel, templates in TEMPLATES:
        pool = sorted({s for t in templates for s in expand(t)} - seen_bank)
        k = PER_GROUP_UNKNOWN if label == UNKNOWN else PER_GROUP
        for s in rng.sample(pool, min(k, len(pool))):
            rows.append({"q": s, "label": label, "channel": channel})
    return rows


def grade(label: str, channel: str | None, got: str | None, got_ch: str | None) -> bool:
    if label == UNKNOWN:
        return got in (None, UNKNOWN, "help")
    return got == label and (channel is None or got_ch == channel)


# ---- 模型调用 --------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [*parsing._LABELS, UNKNOWN]},
        "channel": {"type": "string", "enum": [T, H, N, "none"]},
    },
    "required": ["intent", "channel"],
}


def call(question: str, structured: bool) -> tuple[str, float]:
    payload: dict[str, object] = {
        "model": "qwen3.5:4b",
        "prompt": parsing.build_prompt(question),
        "system": parsing.PARSE_SYSTEM_PROMPT,
        "stream": False,
        "think": False,
        "options": {"num_thread": 8, "num_predict": 160, "temperature": 0.3, "seed": 7},
    }
    if structured:
        payload["format"] = SCHEMA
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("response", ""), time.monotonic() - started


def interpret_free(reply: str) -> tuple[str | None, str | None, bool]:
    """(标签, 通道, 是否可用)。None 表示 parse_reply 拒收（线上等同于保持帮助文案）。"""
    intent = parsing.parse_reply(reply)
    if intent is None:
        return None, None, False
    return intent.kind.value, intent.channel, True


def interpret_json(reply: str) -> tuple[str | None, str | None, bool]:
    try:
        data = json.loads(reply)
        label, ch = data["intent"], data["channel"]
    except (ValueError, KeyError, TypeError):
        return None, None, False
    if label == UNKNOWN or label not in parsing._LABELS:
        return None, None, label == UNKNOWN
    channel = None if ch == "none" else ch
    if parsing._LABELS[label] in parsing._CHANNEL_REQUIRED and channel is None:
        return None, None, False
    return label, channel, True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules-only", action="store_true")
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    if args.probe:
        for q in ("最热那会儿多少度", "帮我点个外卖"):
            for s in (False, True):
                print(s, call(q, s))
        return

    rows = build_set()
    (OUT / "heldout_set.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    for r in rows:
        it = recognise(str(r["q"]))
        r["rule"], r["rule_ch"] = it.kind.value, it.channel
        r["rule_ok"] = grade(r["label"], r["channel"], it.kind.value, it.channel)
        r["rule_help"] = it.kind is IntentKind.HELP

    if not args.rules_only:
        call("预热", False)
        for i, r in enumerate(rows, 1):
            for mode, structured, interp in (("A", False, interpret_free), ("B", True, interpret_json)):
                reply, secs = call(str(r["q"]), structured)
                label, ch, _ = interp(reply)
                r[f"{mode}_raw"], r[f"{mode}_s"] = reply, round(secs, 2)
                r[f"{mode}"], r[f"{mode}_ch"] = label, ch
                r[f"{mode}_ok"] = grade(r["label"], r["channel"], label, ch)
                r[f"{mode}_unusable"] = label is None and r["label"] != UNKNOWN
                # 组合：规则 HELP 才用模型；模型拒收则保持 HELP
                if r["rule_help"]:
                    r[f"combo_{mode}_ok"] = grade(r["label"], r["channel"], label, ch)
                else:
                    r[f"combo_{mode}_ok"] = r["rule_ok"]
            print(f"{i}/{len(rows)} {r['q']} rule={r['rule']} A={r['A']}/{r['A_ch']} B={r['B']}/{r['B_ch']}", flush=True)

    (OUT / "exp_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    summarise(rows, not args.rules_only)


def summarise(rows: list[dict[str, object]], with_model: bool) -> None:
    n = len(rows)
    inscope = [r for r in rows if r["label"] != UNKNOWN]
    oos = [r for r in rows if r["label"] == UNKNOWN]
    def pct(a: int, b: int) -> str:
        return f"{a}/{b} = {a / b:.1%}" if b else "0/0"
    print(f"\n题数 {n}（范围内 {len(inscope)}，范围外 {len(oos)}）")
    print("== 实验 1：只跑规则 ==")
    print("  总体正确", pct(sum(bool(r["rule_ok"]) for r in rows), n))
    print("  范围内正确", pct(sum(bool(r["rule_ok"]) for r in inscope), len(inscope)))
    print("  范围内落空(HELP，交模型)", pct(sum(bool(r["rule_help"]) for r in inscope), len(inscope)))
    wrong = [r for r in inscope if not r["rule_ok"] and not r["rule_help"]]
    print("  范围内**答错**(规则自信地错)", pct(len(wrong), len(inscope)))
    oos_wrong = [r for r in oos if not r["rule_ok"]]
    print("  范围外被规则误接", pct(len(oos_wrong), len(oos)))
    for r in wrong + oos_wrong:
        print(f"    ✗ {r['q']}  期望 {r['label']}/{r['channel']}  规则 {r['rule']}/{r['rule_ch']}")
    if not with_model:
        return
    print("== 实验 2：模型直分类（绕过规则）==")
    for mode, name in (("A", "现行自由文本+parse_reply"), ("B", "JSON Schema 约束")):
        secs = sorted(float(r[f"{mode}_s"]) for r in rows)
        print(f"  [{mode}] {name}")
        print("    总体正确", pct(sum(bool(r[f'{mode}_ok']) for r in rows), n))
        print("    范围内正确", pct(sum(bool(r[f'{mode}_ok']) for r in inscope), len(inscope)))
        print("    范围内拒收/无法解析", pct(sum(bool(r[f'{mode}_unusable']) for r in inscope), len(inscope)))
        print("    范围外正确拒绝", pct(sum(bool(r[f'{mode}_ok']) for r in oos), len(oos)))
        print(f"    耗时 中位 {secs[len(secs)//2]:.2f}s  最长 {secs[-1]:.2f}s")
        print("    组合(规则优先+模型兜底)总体正确", pct(sum(bool(r[f'combo_{mode}_ok']) for r in rows), n))
    print("  A/B 分歧题：")
    for r in rows:
        if r["A_ok"] != r["B_ok"]:
            print(f"    {r['q']} 期望 {r['label']}/{r['channel']} | A {r['A']}/{r['A_ch']} {'✓' if r['A_ok'] else '✗'} raw={str(r['A_raw'])[:40]!r} | B {r['B']}/{r['B_ch']} {'✓' if r['B_ok'] else '✗'}")


if __name__ == "__main__":
    main()
