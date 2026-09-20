"""Tests for ui.widgets.assistant_panel -- no api/controller involved."""

from __future__ import annotations

from ui.widgets.assistant_panel import (
    SOURCE_FALLBACK,
    SOURCE_MODEL,
    SOURCE_MODEL_INTENT,
    SOURCE_TEMPLATE,
    TITLE,
    TITLE_TEMPLATE_ONLY,
    AssistantPanelWidget,
    source_label,
)


def _panel(qtbot) -> AssistantPanelWidget:
    panel = AssistantPanelWidget()
    qtbot.addWidget(panel)
    return panel


# -- source labelling ---------------------------------------------------------


def test_source_labels_distinguish_template_from_model() -> None:
    """The panel shows who wrote the *wording*. Putting that on screen is
    how the "numbers are never the model's" guarantee becomes visible to
    a viewer rather than staying in a design document."""
    assert source_label(SOURCE_TEMPLATE) == "系统"
    assert source_label(SOURCE_MODEL) == "模型改写"
    assert source_label(SOURCE_FALLBACK) == "未识别"
    # 「模型改写」and「模型识别」are different claims about how much of the
    # answer came from the model, and a reader who cannot tell them apart
    # cannot judge how much to trust it.
    assert source_label(SOURCE_MODEL_INTENT) == "模型识别"
    assert source_label(SOURCE_MODEL_INTENT) != source_label(SOURCE_MODEL)


def test_unknown_source_passes_through_rather_than_crashing() -> None:
    assert source_label("something-new") == "something-new"


# -- message flow -------------------------------------------------------------


def test_submitting_emits_the_question_and_shows_it(qtbot) -> None:
    panel = _panel(qtbot)
    seen: list[str] = []
    panel.question_submitted.connect(seen.append)

    panel._input.setText("现在温度多少")
    panel._submit()

    assert seen == ["现在温度多少"]
    assert panel.message_count() == 1
    assert panel._input.text() == ""


def test_blank_input_submits_nothing(qtbot) -> None:
    panel = _panel(qtbot)
    seen: list[str] = []
    panel.question_submitted.connect(seen.append)

    panel._input.setText("   ")
    panel._submit()

    assert seen == []
    assert panel.message_count() == 0


def test_answer_is_appended_after_the_question(qtbot) -> None:
    panel = _panel(qtbot)
    panel.append_question("现在温度多少")
    panel.append_answer("温度现在是 26.4℃。", SOURCE_TEMPLATE)

    assert panel.message_count() == 2


def test_a_later_rephrasing_replaces_rather_than_repeats(qtbot) -> None:
    """A model rephrasing lands seconds after the template answer. Adding
    a second bubble would read as the assistant saying the same thing
    twice; replacing reads as the answer improving."""
    panel = _panel(qtbot)
    panel.append_question("现在温度多少")
    panel.append_answer("温度现在是 26.4℃。", SOURCE_TEMPLATE)
    panel.append_answer("现在温度 26.4℃，还挺舒服的。", SOURCE_MODEL)

    assert panel.message_count() == 2


def test_a_new_question_starts_a_fresh_answer_bubble(qtbot) -> None:
    panel = _panel(qtbot)
    panel.append_question("q1")
    panel.append_answer("a1", SOURCE_TEMPLATE)
    panel.append_question("q2")
    panel.append_answer("a2", SOURCE_TEMPLATE)

    assert panel.message_count() == 4


def test_clear_removes_every_message(qtbot) -> None:
    panel = _panel(qtbot)
    panel.append_question("q")
    panel.append_answer("a", SOURCE_TEMPLATE)
    panel.clear()

    assert panel.message_count() == 0


def test_answer_without_a_preceding_question_still_shows(qtbot) -> None:
    panel = _panel(qtbot)
    panel.append_answer("欢迎使用。", SOURCE_TEMPLATE)

    assert panel.message_count() == 1


# -- model availability is visible, not just logged ---------------------------


def test_panel_starts_assuming_no_model(qtbot) -> None:
    panel = _panel(qtbot)
    assert panel.model_available() is False


def test_attached_model_is_announced_in_the_title_and_transcript(qtbot) -> None:
    panel = _panel(qtbot)
    panel.set_model_status(True)

    assert panel.title() == TITLE
    assert panel.model_available() is True
    assert panel.message_count() == 1


def test_missing_model_says_so_and_gives_the_reason(qtbot) -> None:
    """Without this the panel looks identical whether the model is absent
    or silently failing -- every answer just stays labelled 「系统」."""
    panel = _panel(qtbot)
    panel.set_model_status(False, "ConnectionRefusedError: 拒绝连接")

    assert panel.title() == TITLE_TEMPLATE_ONLY
    assert panel.model_available() is False
    body = panel._messages_layout.itemAt(0).widget()._body.text()
    assert "只用模板" in body
    assert "拒绝连接" in body


def test_the_status_notice_is_not_mistaken_for_an_answer(qtbot) -> None:
    """It must not become the bubble a later rephrasing overwrites."""
    panel = _panel(qtbot)
    panel.set_model_status(True)
    panel.append_answer("这是一条真答案。", SOURCE_TEMPLATE)

    assert panel.message_count() == 2


# -- 答案底下的动作按钮（2026-09-18） -----------------------------------------


def _action_buttons(panel) -> list:
    from PyQt6.QtWidgets import QPushButton

    return [
        b for b in panel.findChildren(QPushButton) if b.objectName() == "answerAction"
    ]


def test_an_answer_with_no_tag_gets_no_button(qtbot) -> None:
    """默认不给按钮——这是绝大多数答案。"""
    panel = AssistantPanelWidget()
    qtbot.addWidget(panel)
    panel.set_action_handler("cloud_sync", lambda: None)

    panel.append_question("现在温度多少")
    panel.append_answer("温度 25.03 °C", "template")

    assert _action_buttons(panel) == []


def test_a_tagged_answer_gets_one_button_that_calls_the_handler(qtbot) -> None:
    clicks: list[str] = []
    panel = AssistantPanelWidget()
    qtbot.addWidget(panel)
    panel.set_action_handler("cloud_sync", lambda: clicks.append("go"))

    panel.append_question("把数据传上去")
    panel.append_answer("有 12 个时段还没上传。", "template", "cloud_sync")

    buttons = _action_buttons(panel)
    assert len(buttons) == 1
    assert buttons[0].text() == "导出并上传"
    assert clicks == []  # 光显示不算触发
    buttons[0].click()
    assert clicks == ["go"]


def test_a_late_rephrasing_does_not_stack_a_second_button(qtbot) -> None:
    """迟到的模型改写是就地重写同一个气泡，按钮不能再叠一个。"""
    panel = AssistantPanelWidget()
    qtbot.addWidget(panel)
    panel.set_action_handler("cloud_sync", lambda: None)
    panel.append_question("把数据传上去")
    panel.append_answer("有 12 个时段还没上传。", "template", "cloud_sync")

    panel.append_answer("还有 12 个时段没传，点按钮就能传。", "model", "cloud_sync")

    assert len(_action_buttons(panel)) == 1


def test_a_tag_with_no_handler_installed_shows_no_button(qtbot) -> None:
    """无界面启动器不装处理器；那时按钮不该出现，也不该报错——
    它在一个聊天面板里，弹异常不是按钮该有的行为。"""
    panel = AssistantPanelWidget()
    qtbot.addWidget(panel)

    panel.append_question("把数据传上去")
    panel.append_answer("有 12 个时段还没上传。", "template", "cloud_sync")

    assert _action_buttons(panel) == []


def test_an_unknown_tag_is_ignored(qtbot) -> None:
    panel = AssistantPanelWidget()
    qtbot.addWidget(panel)
    panel.set_action_handler("cloud_sync", lambda: None)

    panel.append_question("随便问问")
    panel.append_answer("答案", "template", "something_else")

    assert _action_buttons(panel) == []


def test_the_two_cloud_actions_have_their_own_buttons(qtbot) -> None:
    """两个按钮各调各的处理器——接错了会变成"想看一眼却传了一轮"。"""
    calls: list[str] = []
    panel = AssistantPanelWidget()
    qtbot.addWidget(panel)
    panel.set_action_handler("cloud_sync", lambda: calls.append("sync"))
    panel.set_action_handler("cloud_view", lambda: calls.append("view"))

    panel.append_question("把数据传上去")
    panel.append_answer("有 3 个时段还没上传。", "template", "cloud_sync")
    panel.append_question("云上有什么")
    panel.append_answer("可以看云上已经传了哪些归档。", "template", "cloud_view")

    buttons = _action_buttons(panel)
    assert [b.text() for b in buttons] == ["导出并上传", "查看云端归档"]
    for b in buttons:
        b.click()
    assert calls == ["sync", "view"]
