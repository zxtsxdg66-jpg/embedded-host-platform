"""把真人问过的每一句话记下来，供日后补题库与分析。

为什么需要它
------------
问答的题库有两套：87 句拟合题库（词表照着它的错答补过，因此它的 100% 只是拟合）
与 148 句留出题库（模板展开生成，不等于真人问法）。两套都不是真人在真实节奏下
说出来的话，而项目里**真正有价值的缺陷全部来自真人试用**：2026-09-08 连问两句
答案错位、09-09 说"开风扇"规则认不出、09-15 一句话里问两件事被丢掉一半。
这些题库一条也测不出来。

以前这些句子问完就没了——系统不记录提问。于是每次想改进都要专门坐下来"想测试用例"，
而想出来的句子仍然是模板。这个模块把顺序倒过来：**平时正常用，用完自然攒出一批真实语料**。

记什么
------
一问一答一条 JSON 行，含提问原话、立刻返回的模板答案、几秒后迟到的模型改写、
识别出的意图与通道、是否执行了指令、以及迟到答案的耗时。分析时最有用的是三类行：
``final.source == "fallback"``（没听懂）、``intent`` 与预期不符（听错了）、
以及 ``applied`` 为真却不该执行的（误动作）。

三条纪律
--------
1. **绝不向外抛异常。** 日志写不动（磁盘满、路径没权限）也不能把问答带下水——
   与"模型缺席时问答照常工作"是同一条原则。所有写入都吞掉异常并记一次计数。
2. **只写本地文件。** 不上板载屏（屏幕只显示系统能负责的读数，日志不是），
   不推给手机，不进网关的任何端点。
3. **不入库。** 输出目录已在 `.gitignore` 里排除——里面是真人说过的话。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "assistant"
"""默认落点：仓库根目录下的 logs/assistant/，按天分文件。"""


class _AnswerLike(Protocol):
    """``service.assistant.models.Answer`` 里本模块用得上的那部分。

    写成 Protocol 而不是直接 import Answer，是为了让测试能用一个假对象驱动，
    也让本模块不必依赖 service 的具体类型——它是组合根里的工具，不是服务层的一部分。
    """

    text: str

    @property
    def source(self) -> Any: ...

    @property
    def intent(self) -> Any: ...

    @property
    def facts(self) -> Any: ...


def _describe(answer: _AnswerLike | None) -> dict[str, Any]:
    """把一个 Answer 摊平成可 JSON 化的字段，任何一处取不到都不算错。"""
    if answer is None:
        return {}
    source = getattr(answer, "source", None)
    intent = getattr(answer, "intent", None)
    facts = getattr(answer, "facts", None)
    kind = getattr(intent, "kind", None)
    return {
        "text": getattr(answer, "text", ""),
        "source": getattr(source, "value", None),
        "intent": getattr(kind, "value", None),
        "channel": getattr(intent, "channel", None),
        "applied": getattr(facts, "applied", None),
    }


@dataclass
class _Pending:
    """已经问出口、还在等模型改写的那一条。"""

    record: dict[str, Any]
    asked_at: float
    moment: datetime
    """提问发生的时刻。**落盘时按它归档，而不是按写盘时刻**——

    一条记录要等模型改写几秒才落盘，跨零点时按写盘时刻归档会把昨晚的最后一问
    写进今天的文件；配对落盘的那一条更是必然错位（提问在昨天、改写在今天）。
    日志是拿来回溯"那天问了什么"的，归错一天就白记了。"""


@dataclass
class QuestionLog:
    """一问一答写一行 JSONL。线程安全，且从不抛异常。

    ``run_all`` 里网关跑在另一个线程，桌面端在 Qt 主线程，两边都可能写，
    所以用一把锁护住"挂起的那条"与文件追加。
    """

    log_dir: Path = DEFAULT_LOG_DIR
    clock: Any = None
    """取当前时间的可调用对象，默认 ``datetime.now``。测试可注入固定时钟。"""

    _pending: _Pending | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )
    failures: int = field(default=0, init=False)
    """写入失败的次数。不抛异常，但也不假装没发生过。"""

    def _now(self) -> datetime:
        clock = self.clock or datetime.now
        return clock()

    def record_question(
        self, question: str, answer: _AnswerLike | None, *, source: str = "pc"
    ) -> None:
        """记下一次提问与它**立刻**得到的答案。

        ``source`` 区分桌面端与手机端。若上一条还在等模型改写，先把它原样落盘——
        新问题进来时旧的改写已被助手取消（见 ``Assistant._start_rephrasing``），
        再等下去只会等到一条永远不来的结果。
        """
        try:
            moment = self._now()
            record = {
                "ts": moment.isoformat(timespec="seconds"),
                "from": source,
                "question": question,
                "immediate": _describe(answer),
            }
            with self._lock:
                stale = self._pending
                self._pending = _Pending(
                    record=record, asked_at=self._monotonic(), moment=moment
                )
                if stale is not None:
                    self._write(stale.record, stale.moment)
        except Exception:  # noqa: BLE001 - 见模块文档第 1 条纪律
            self.failures += 1

    def record_late_answer(self, text: str, answer_source: str) -> None:
        """记下几秒后迟到的模型改写，并把这一条落盘。

        只有文本与来源两个字段——这正是启动器手上有的东西
        （``make_poll_once`` 的 ``on_assistant_answer`` 形状是 ``(text, source)``）。
        没有挂起的提问就什么都不做：迟到答案总是跟着某一次提问来的，
        没有对应的提问说明日志刚启动或上一条已落盘。
        """
        try:
            with self._lock:
                pending = self._pending
                self._pending = None
                if pending is None:
                    return
                pending.record["final"] = {"text": text, "source": answer_source}
                pending.record["late_ms"] = int(
                    (self._monotonic() - pending.asked_at) * 1000
                )
                self._write(pending.record, pending.moment)
        except Exception:  # noqa: BLE001
            self.failures += 1

    def flush(self) -> None:
        """把还挂着的那条落盘。退出前调用，避免最后一问丢失。"""
        try:
            with self._lock:
                pending = self._pending
                self._pending = None
                if pending is not None:
                    self._write(pending.record, pending.moment)
        except Exception:  # noqa: BLE001
            self.failures += 1

    # -- 内部 ---------------------------------------------------------------

    @staticmethod
    def _monotonic() -> float:
        import time

        return time.monotonic()

    def _path_for(self, moment: datetime) -> Path:
        return self.log_dir / f"{moment:%Y%m%d}.jsonl"

    def _write(self, record: dict[str, Any], moment: datetime) -> None:
        """追加一行到 ``moment`` 那天的文件。目录不存在就建，写失败只计数不抛。"""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            path = self._path_for(moment)
            line = json.dumps(record, ensure_ascii=False)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:  # noqa: BLE001
            self.failures += 1


__all__ = ["DEFAULT_LOG_DIR", "QuestionLog"]
