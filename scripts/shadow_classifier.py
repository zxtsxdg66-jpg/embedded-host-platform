"""影子分类：规则判出的提问，后台再让模型独立分类一次——只记录，不改回答（2026-09-29）。

起因：用户问"温湿度多少"只得到湿度。规则认出了"湿度"这个词，模型因此从未被问到；
单独把这句话交给模型分类，3 次都给出温度＋湿度。规则优先的管线里，规则一旦（部分）认出，
就再没有人检查它漏了什么，而我们不可能预先想到所有问法。

做法是把"模型怎么看"变成可观测的：规则判出一个**提问**时，
等助手自己的模型任务做完、模型空闲了，再用同一套分类提示词把原话交给模型，
把两边的判定并排写进 ``logs/assistant/shadow_YYYYMMDD.jsonl``，
由 :func:`compare` 归成几类（一致、模型认出的通道更多、问法不同……）。
攒下来的分歧就是补规则、训练本地模型的真人语料。

**它不改变任何回答**，这是这一步的全部前提：

- 放在 ``scripts/``、挂在问答日志上，``src/`` 里的助手一行未动，
  各套基线因此在构造上不受影响；
- 用自己的模型客户端，只在助手的客户端空闲时提交；有新问题进来立即取消
  正在跑的这一次（本机一次分类约 4.4 s，不让它挤占用户下一问的改写）；
  排队只留最新一句，被挤掉的记为 superseded；
- 只看规则判出的提问（``AnswerSource.TEMPLATE`` 且意图属于
  :data:`SHADOWED_KINDS`）。指令已有模型复核（docs/decisions/03-intent.md），
  规则认不出的句子本来就交给了模型，都不重复。

是否让模型的分歧真正改变回答（例如自动补上规则漏掉的通道），等这里攒到真人数据再定，
见 docs/decisions/03-intent.md。
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from service.assistant import parsing
from service.assistant.llm_port import LlmClient
from service.assistant.models import Answer, AnswerSource, Intent, IntentKind

SHADOWED_KINDS = frozenset(
    {
        IntentKind.CURRENT_VALUE,
        IntentKind.MINIMUM,
        IntentKind.MAXIMUM,
        IntentKind.AVERAGE,
        IntentKind.ALARM_STATE,
        IntentKind.THRESHOLD_INFO,
        IntentKind.FAN_STATE,
        IntentKind.DEVICE_LIST,
        IntentKind.SAMPLE_COUNT,
    }
)
"""模型分类标签里也有的提问类意图。

其余（帮助、拒绝、身份等）模型没有对应标签，比不出东西。"""

DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "assistant"
"""与问答日志同一个目录。

不从 ``question_log`` 导入：本模块既会被启动器以平级方式导入，也会被测试以
``scripts.`` 包路径导入，平级 import 在后一种下找不到（2026-09-17 的同类坑）。"""

TIMEOUT_SECONDS = 30.0
TICK_SECONDS = 0.1


def rule_channels(answer: Answer) -> list[str]:
    """规则这一问实际答了哪些通道：多通道展开的回答每段各有一份事实。"""
    if answer.all_facts:
        channels = [f.channel for f in answer.all_facts if f.channel]
    elif answer.intent is not None and answer.intent.channel:
        channels = [answer.intent.channel]
    else:
        channels = []
    return list(dict.fromkeys(channels))


def compare(
    rule_kind: IntentKind, rule_chs: list[str], candidates: tuple[Intent, ...]
) -> str:
    """把两边的判定归成一类。

    - ``agree``：问法与通道都相同；
    - ``model_more_channels``：问法相同，模型认出的通道包含规则的、且更多
      （"温湿度"那一类）；
    - ``model_fewer_channels`` / ``channel_differs``：问法相同，通道少了或不同；
    - ``kind_differs``：模型认为问的是另一件事；
    - ``model_unsure``：模型给了几个不同的候选；
    - ``model_unknown``：模型认不出，或回复无法解析。
    """
    if not candidates:
        return "model_unknown"
    if len({c.kind for c in candidates}) > 1:
        return "model_unsure"
    if candidates[0].kind is not rule_kind:
        return "kind_differs"
    model_chs = {c.channel for c in candidates if c.channel}
    rule_set = set(rule_chs)
    if model_chs == rule_set:
        return "agree"
    if model_chs > rule_set:
        return "model_more_channels"
    if model_chs < rule_set:
        return "model_fewer_channels"
    return "channel_differs"


@dataclass
class _Job:
    question: str
    source: str
    rule_kind: IntentKind
    rule_channels: list[str]
    asked_at: datetime


class ShadowClassifier:
    """见模块文档。线程安全，从不抛异常；:meth:`start` 之后由自己的后台线程推进。"""

    def __init__(
        self,
        client: LlmClient,
        assistant_busy: Callable[[], bool],
        *,
        log_dir: Path = DEFAULT_LOG_DIR,
        clock: Callable[[], datetime] = datetime.now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._assistant_busy = assistant_busy
        self._log_dir = log_dir
        self._clock = clock
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._queued: _Job | None = None
        self._running: _Job | None = None
        self._cancel_running = False
        self._reply = ""
        self._submitted_at = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.failures = 0
        """写日志失败的次数。不抛异常，但也不假装没发生过。"""

    # -- 入口：每次提问都要经过这里 -------------------------------------------

    def offer(self, question: str, answer: Answer | None, source: str = "pc") -> None:
        """每一问都调用。先让出模型（取消在跑的影子分类），再决定这一问要不要排队。"""
        with self._lock:
            if self._running is not None:
                self._cancel_running = True
            if self._queued is not None:
                self._write_outcome(self._queued, "superseded")
                self._queued = None
            if (
                answer is None
                or answer.source is not AnswerSource.TEMPLATE
                or answer.intent is None
                or answer.intent.kind not in SHADOWED_KINDS
            ):
                return
            self._queued = _Job(
                question=question,
                source=source,
                rule_kind=answer.intent.kind,
                rule_channels=rule_channels(answer),
                asked_at=self._clock(),
            )

    # -- 推进：由后台线程（或测试）反复调用 ------------------------------------

    def step(self) -> None:
        """推进一拍：收回结果、处理取消与超时，或在模型空闲时提交排队的那一句。"""
        with self._lock:
            if self._running is not None:
                self._advance_running()
                return
            if self._queued is None or self._client.is_busy():
                return
            if self._assistant_busy():
                return
            job, self._queued = self._queued, None
            if not self._client.submit(
                parsing.build_prompt(job.question), system=parsing.PARSE_SYSTEM_PROMPT
            ):
                self._write_outcome(job, "unavailable")
                return
            self._running = job
            self._reply = ""
            self._submitted_at = self._monotonic()

    def _advance_running(self) -> None:
        job = self._running
        assert job is not None
        if self._cancel_running:
            self._client.cancel()
            self._write_outcome(job, "superseded")
            self._clear_running()
            return
        chunk = self._client.poll()
        if chunk:
            self._reply += chunk
        if self._client.is_busy():
            if self._monotonic() - self._submitted_at > TIMEOUT_SECONDS:
                self._client.cancel()
                self._write_outcome(job, "timeout")
                self._clear_running()
            return
        seconds = self._monotonic() - self._submitted_at
        candidates = parsing.parse_candidates(self._reply)
        self._write(
            job,
            {
                "outcome": "classified",
                "model_reply": self._reply.strip(),
                "model": [
                    {"kind": c.kind.value, "channel": c.channel} for c in candidates
                ],
                "verdict": compare(job.rule_kind, job.rule_channels, candidates),
                "seconds": round(seconds, 2),
            },
        )
        self._clear_running()

    def _clear_running(self) -> None:
        self._running = None
        self._cancel_running = False
        self._reply = ""

    # -- 后台线程 ------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="shadow-classifier", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        with self._lock:
            if self._running is not None:
                self._client.cancel()

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self.step()
            except Exception:  # noqa: BLE001 —— 影子分类出错不得影响任何回答
                self.failures += 1

    # -- 写日志 --------------------------------------------------------------

    def _write_outcome(self, job: _Job, outcome: str) -> None:
        self._write(job, {"outcome": outcome})

    def _write(self, job: _Job, extra: dict[str, Any]) -> None:
        record = {
            "asked_at": job.asked_at.isoformat(timespec="seconds"),
            "source": job.source,
            "question": job.question,
            "rule": {"kind": job.rule_kind.value, "channels": job.rule_channels},
            **extra,
        }
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            path = self._log_dir / f"shadow_{job.asked_at:%Y%m%d}.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            self.failures += 1


__all__ = ["SHADOWED_KINDS", "ShadowClassifier", "compare", "rule_channels"]
