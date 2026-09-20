"""AssistantPanelWidget: the environment Q&A chat panel.

Passive View, like every widget in this package: it holds no reference to
MainController or ApiInterface and imports nothing from ``service`` --
the answer's origin crosses this boundary as a plain string, exactly as
the fan mode does in ventilation_panel.py.

The panel deliberately labels **who wrote the wording** on every answer
("系统" for a template, "模型改写" for a language-model rephrasing). That
is not decoration: the platform's guarantee is that numbers always come
from measured data while only the sentence around them may be reworded,
and showing which is which puts that guarantee on screen instead of
leaving it in a design document. A viewer can see at a glance that the
figures were never the model's to invent.

Answers arrive by signal rather than return value because a model
rephrasing may land seconds after the question -- :meth:`append_answer`
is called once immediately with the template answer, and possibly again
later with the reworded one, which replaces it in place.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.theme import set_class

SOURCE_TEMPLATE = "template"
SOURCE_MODEL = "model"
SOURCE_MODEL_INTENT = "model_intent"
SOURCE_FALLBACK = "fallback"

_SOURCE_LABELS: dict[str, str] = {
    SOURCE_TEMPLATE: "系统",
    SOURCE_MODEL: "模型改写",
    SOURCE_MODEL_INTENT: "模型识别",
    SOURCE_FALLBACK: "未识别",
}
"""Two distinct model labels on purpose: 「模型改写」 means the model
reworded a sentence the system had already composed, 「模型识别」 means it
worked out what was being asked and the sentence itself is the system's.
A reader who cannot tell those apart cannot judge how much to trust the
answer -- and they are trustworthy to different degrees."""

PLACEHOLDER = "问点什么，例如：现在温度多少 / 噪声超标了吗"

TITLE = "环境问答"
TITLE_TEMPLATE_ONLY = "环境问答（仅模板）"
"""Shown when no language model is attached.

Worth putting in the title rather than only in a console line: whether the
model is connected changes nothing about correctness, but it changes what
a user should expect to see -- without it every answer stays labelled
「系统」 forever. Leaving that invisible cost a real debugging session,
where the answers looked identical to a broken model."""


def source_label(source: str) -> str:
    """Chinese label for an answer source, unknown values passed through."""
    return _SOURCE_LABELS.get(source, source)


class _Bubble(QWidget):
    """One message: a small role/source line above the text itself."""

    def __init__(self, text: str, role: str, source: str = "") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(2)

        caption = role if not source else f"{role} · {source_label(source)}"
        self._caption = QLabel(caption)
        set_class(self._caption, "bubbleCaption")

        self._body = QLabel(text)
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        set_class(self._body, "bubbleBody")

        layout.addWidget(self._caption)
        layout.addWidget(self._body)

        self._action: QPushButton | None = None

    def update_answer(self, text: str, source: str) -> None:
        """Rewrite this bubble in place, for a late model rephrasing."""
        self._caption.setText(f"助手 · {source_label(source)}")
        self._body.setText(text)

    def set_action(self, label: str, on_click: Callable[[], None]) -> None:
        """Put one action button under this answer (2026-09-18).

        The whole of the assistant's reach into anything irreversible is
        this button: the model proposes, the sentence explains, and a
        person clicking is what starts the work. See
        docs/02_Architecture/History_And_Cloud_Design.md section 6.1 for
        why uploading is offered this way rather than being executed on
        the strength of a sentence.

        At most one button per bubble, and it is created once: a late
        model rephrasing rewrites the text through
        :meth:`update_answer` and must not stack a second button under it.
        """
        if self._action is not None:
            return
        button = QPushButton(label)
        button.setObjectName("answerAction")
        button.clicked.connect(lambda: on_click())
        self._action = button
        layout = self.layout()
        if layout is not None:
            layout.addWidget(button)

    def has_action(self) -> bool:
        return self._action is not None


_ACTION_LABELS: dict[str, str] = {
    "cloud_sync": "导出并上传",
    "cloud_view": "查看云端归档",
}
"""Tag -> button label. The tag matches ``IntentKind.CLOUD_SYNC_HINT``'s
value, but is compared as a string: ``ui`` must not import the service
layer's enum (see src/ui/README.md 的分层说明)."""


class AssistantPanelWidget(QGroupBox):
    """Chat panel for the environment assistant."""

    question_submitted = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(TITLE, parent)
        self._last_answer: _Bubble | None = None
        self._model_available = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 14, 10, 10)
        outer.setSpacing(8)

        self._messages = QWidget()
        self._messages_layout = QVBoxLayout(self._messages)
        self._messages_layout.setContentsMargins(0, 0, 0, 0)
        self._messages_layout.setSpacing(4)
        self._messages_layout.addStretch(1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._messages)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        outer.addWidget(self._scroll, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._input = QLineEdit()
        self._input.setPlaceholderText(PLACEHOLDER)
        self._input.returnPressed.connect(self._submit)
        self._action_handlers: dict[str, Callable[[], None]] = {}
        self._send = QPushButton("发送")
        self._send.clicked.connect(self._submit)
        row.addWidget(self._input, 1)
        row.addWidget(self._send)
        outer.addLayout(row)

    def set_model_status(self, available: bool, detail: str = "") -> None:
        """Record whether a language model is attached, and say so.

        Called once at start-up by the composition root. Posts a short
        notice into the transcript as well as retitling, because the title
        is easy to overlook and the distinction matters for what the user
        should expect: with no model every answer stays labelled 「系统」,
        which is correct but looks identical to a model that is silently
        failing.
        """
        self._model_available = available
        self.setTitle(TITLE if available else TITLE_TEMPLATE_ONLY)
        if available:
            notice = "本地模型已接入。回答会先出模板版本，几秒后自动替换为改写版本。"
        else:
            notice = "未接入本地模型，回答只用模板措辞（内容同样准确）。"
            if detail:
                notice += f"\n原因：{detail}"
        self._add(_Bubble(notice, "提示"))
        self._last_answer = None

    def model_available(self) -> bool:
        """Whether a language model was reported as attached."""
        return self._model_available

    # -- interaction ----------------------------------------------------

    def _submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.append_question(text)
        self.question_submitted.emit(text)

    def append_question(self, text: str) -> None:
        """Show the user's question."""
        self._last_answer = None
        self._add(_Bubble(text, "你"))

    def append_answer(self, text: str, source: str, action: str = "") -> None:
        """Show an answer, or replace the previous one for this question.

        Replacing rather than appending is what makes a late model
        rephrasing read as an improvement to the same answer instead of
        the assistant saying the same thing twice.

        ``action`` names an offer to attach as a button (currently only
        ``"cloud_sync"``). It is a plain string rather than an imported
        enum on purpose: ``ui`` reads the tag, never the service-layer
        type behind it. Empty means no button, which is every answer but
        one.
        """
        if self._last_answer is not None:
            self._last_answer.update_answer(text, source)
            self._offer_action(self._last_answer, action)
            return
        bubble = _Bubble(text, "助手", source)
        self._last_answer = bubble
        self._add(bubble)
        self._offer_action(bubble, action)

    def _offer_action(self, bubble: _Bubble, action: str) -> None:
        """Attach the button for ``action``, if there is one to attach.

        Silently does nothing for an unknown tag, and for a known tag with
        no handler installed. Both are states a launcher can legitimately
        be in -- ``run_api_server`` has no desktop at all -- and neither is
        worth an error in a chat panel.
        """
        if not action or bubble.has_action():
            return
        offer = _ACTION_LABELS.get(action)
        handler = self._action_handlers.get(action)
        if offer is None or handler is None:
            return
        bubble.set_action(offer, handler)

    def set_action_handler(self, action: str, handler: Callable[[], None]) -> None:
        """Install what a given action's button does when clicked.

        Injected from outside rather than emitted as a signal because the
        work behind it -- launching the upload script as a subprocess --
        must not be started, or even named, inside ``ui``. The composition
        root passes a callable in; this widget only knows there is one.
        """
        self._action_handlers[action] = handler

    def _add(self, bubble: _Bubble) -> None:
        # Insert before the trailing stretch so messages stay top-aligned
        # while the panel is still mostly empty.
        self._messages_layout.insertWidget(self._messages_layout.count() - 1, bubble)
        scrollbar = self._scroll.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())

    def message_count(self) -> int:
        """Number of bubbles currently shown (excludes the stretch item)."""
        return self._messages_layout.count() - 1

    def clear(self) -> None:
        """Remove every message."""
        while self._messages_layout.count() > 1:
            item = self._messages_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self._last_answer = None
