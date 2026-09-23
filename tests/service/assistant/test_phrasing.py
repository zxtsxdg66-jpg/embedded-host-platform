"""Templates, and the number-grounding check that guards model output.

``numbers_are_grounded`` is the runtime backstop for this feature's
central guarantee -- that no figure a user reads was invented. Its tests
are therefore the most important ones in this package.
"""

from service.assistant.models import AnswerSource, CheckVerdict, Facts, IntentKind
from service.assistant.phrasing import (
    ANNOUNCE_REFUSAL_TEXT,
    DELETE_REFUSAL_TEXT,
    HELP_TEXT,
    choose,
    judge,
    numbers_are_grounded,
    render,
)

_READING = Facts(
    kind=IntentKind.CURRENT_VALUE,
    channel="noise",
    channel_label="噪声",
    unit="dB",
    value=76.3,
    minimum=60.0,
    maximum=82.5,
    average=71.25,
    sample_count=200,
    threshold=80.0,
    threshold_is_maximum=True,
    triggered=False,
)


# -- number grounding ---------------------------------------------------------


def test_text_without_numbers_is_always_grounded() -> None:
    assert numbers_are_grounded("噪声处于正常范围。", _READING)


def test_numbers_taken_from_the_facts_are_accepted() -> None:
    assert numbers_are_grounded("噪声现在 76.3dB，阈值 80dB。", _READING)


def test_a_citations_digits_do_not_count_as_invented() -> None:
    """"GB 37488—2019" carries digits that are not measurements. Without
    treating the citation as a fact, every threshold answer would fail
    its own grounding check -- which is exactly what happened when the
    citation was hard-coded in the template."""
    facts = Facts(
        kind=IntentKind.THRESHOLD_INFO,
        channel_label="噪声",
        unit="dB",
        threshold=80.0,
        citation="GB 37488—2019",
    )
    assert numbers_are_grounded("噪声阈值 80dB，依据 GB 37488—2019。", facts)


def test_an_invented_number_is_rejected() -> None:
    """The exact failure this check exists for: a plausible figure the
    data never produced."""
    assert not numbers_are_grounded("噪声现在 76.3dB，标准是 75dB。", _READING)


def test_a_rounded_number_is_rejected() -> None:
    """76 and 76.3 are different claims on screen even though they are
    close in value, so grounding compares rendered forms, not floats."""
    assert not numbers_are_grounded("噪声现在 76dB。", _READING)


def test_integer_valued_facts_match_without_a_decimal_point() -> None:
    """So "共 200 个采样点" passes against sample_count=200."""
    assert numbers_are_grounded("一共 200 个采样点。", _READING)


def test_any_number_is_ungrounded_when_there_are_no_facts() -> None:
    assert not numbers_are_grounded("温度是 25 度。", None)
    assert numbers_are_grounded("没有数据。", None)


# -- choosing between template and model --------------------------------------


def test_no_model_text_yields_the_template() -> None:
    text, source = choose("模板答案", None, _READING)
    assert text == "模板答案"
    assert source is AnswerSource.TEMPLATE


def test_grounded_model_text_is_accepted() -> None:
    # 改写样例刻意不带"一切正常"：模板已不再声明状态，凭空加判断会被
    # _adds_an_unsupported_judgement 拦下——那是另一条用例守的事。
    text, source = choose("模板答案", "噪声 76.3dB。", _READING)
    assert text == "噪声 76.3dB。"
    assert source is AnswerSource.MODEL


def test_ungrounded_model_text_falls_back_to_the_template() -> None:
    text, source = choose("模板答案", "噪声 99.9dB，快超标了。", _READING)
    assert text == "模板答案"
    assert source is AnswerSource.TEMPLATE


def test_empty_model_text_falls_back_to_the_template() -> None:
    assert choose("模板答案", "   ", _READING)[1] is AnswerSource.TEMPLATE


# -- templates ----------------------------------------------------------------


def test_a_normal_reading_says_only_the_reading() -> None:
    """报警说，正常不说。不对称是有意的：越限是无论如何都要知道的事，
    "一切正常"可以由沉默表达。原先两侧都说，于是一个只问了读数的问题，
    回来的是读数加一句没人问的判断。"""
    text = render(_READING)
    assert "76.3dB" in text
    assert "正常" not in text


def test_a_reading_over_the_limit_always_says_so() -> None:
    """沉默只用来表达正常，绝不用来表达告警。"""
    from dataclasses import replace as _replace

    text = render(_replace(_READING, triggered=True))
    assert "76.3dB" in text
    assert "已超过报警阈值" in text


def test_alarm_state_when_triggered_names_the_threshold() -> None:
    facts = Facts(
        kind=IntentKind.ALARM_STATE,
        channel="noise",
        channel_label="噪声",
        unit="dB",
        value=85.0,
        threshold=80.0,
        threshold_is_maximum=True,
        triggered=True,
    )
    text = render(facts)
    assert "85.0dB" in text
    assert "80dB" in text
    assert "报警" in text


def test_threshold_info_cites_the_standard_when_one_is_supplied() -> None:
    """The citation is a *fact* supplied by retrieval, not template prose
    -- so the template prints whatever it is given and omits the clause
    when there is none, rather than deciding for itself which channel has
    an authority behind it."""
    noise = Facts(
        kind=IntentKind.THRESHOLD_INFO,
        channel="noise",
        channel_label="噪声",
        unit="dB",
        threshold=80.0,
        citation="GB 37488—2019",
    )
    temperature = Facts(
        kind=IntentKind.THRESHOLD_INFO,
        channel="temperature",
        channel_label="温度",
        unit="℃",
        threshold=35.0,
    )
    assert "GB 37488" in render(noise)
    assert "GB 37488" not in render(temperature)


def test_a_two_sided_band_is_stated_as_a_range() -> None:
    """Rendering only the ceiling would hide a floor equally able to
    raise an alarm -- the failure the humidity channel had until
    2026-09-08."""
    facts = Facts(
        kind=IntentKind.THRESHOLD_INFO,
        channel="humidity",
        channel_label="湿度",
        unit="%RH",
        threshold=75.0,
        threshold_low=30.0,
        threshold_high=75.0,
    )
    text = render(facts)

    assert "30" in text
    assert "75" in text


def test_a_normal_reading_on_a_banded_channel_names_both_bounds() -> None:
    facts = Facts(
        kind=IntentKind.ALARM_STATE,
        channel="humidity",
        channel_label="湿度",
        unit="%RH",
        value=62.0,
        threshold=75.0,
        threshold_low=30.0,
        threshold_high=75.0,
        triggered=False,
    )
    text = render(facts)

    assert "30" in text
    assert "75" in text
    assert "正常" in text


def test_unavailable_channel_says_so_plainly() -> None:
    facts = Facts(
        kind=IntentKind.CURRENT_VALUE,
        available=False,
        channel="humidity",
        channel_label="湿度",
    )
    text = render(facts)
    assert "湿度" in text
    assert "没有有效读数" in text


def test_fan_template_includes_reason_and_mode() -> None:
    facts = Facts(
        kind=IntentKind.FAN_STATE,
        fan_running=True,
        fan_reason="温度 31.0℃ 高于通风阈值 30℃",
        fan_mode="AUTO",
    )
    text = render(facts)
    assert "正在运行" in text
    assert "自动" in text
    assert "31.0℃" in text


def test_fan_template_when_ventilation_is_not_enabled() -> None:
    text = render(Facts(kind=IntentKind.FAN_STATE, available=False))
    assert "没有启用" in text


def test_device_list_template() -> None:
    facts = Facts(kind=IntentKind.DEVICE_LIST, device_ids=("a", "b"))
    text = render(facts)
    assert "2 个设备" in text
    assert "a、b" in text


def test_empty_device_list() -> None:
    assert "没有" in render(Facts(kind=IntentKind.DEVICE_LIST))


def test_help_template_is_the_capability_menu() -> None:
    assert render(Facts(kind=IntentKind.HELP)) == HELP_TEXT


def test_every_template_is_grounded_in_its_own_facts() -> None:
    """The templates must satisfy the same rule they enforce on a model:
    if a template ever printed a number not in Facts, the check would be
    inconsistent with the system's own output."""
    for facts in (
        _READING,
        Facts(kind=IntentKind.DEVICE_LIST, device_ids=("a", "b")),
        Facts(
            kind=IntentKind.THRESHOLD_INFO,
            channel_label="噪声",
            unit="dB",
            threshold=80.0,
            citation="GB 37488—2019",
        ),
        Facts(kind=IntentKind.MAXIMUM, channel_label="温度", unit="℃", maximum=37.2),
        # Control confirmations and refusals hold themselves to the same
        # rule -- including the out-of-range refusal, which quotes the
        # value the user asked for and therefore has to carry it.
        Facts(kind=IntentKind.FAN_ON, applied=True, fan_running=True),
        Facts(kind=IntentKind.FAN_AUTO, applied=True, fan_running=False),
        Facts(
            kind=IntentKind.SET_VENT_THRESHOLD,
            applied=True,
            channel_label="温度",
            unit="℃",
            threshold=28.0,
            fan_running=False,
        ),
        Facts(kind=IntentKind.FAN_ON, applied=False, rejection="no_controller"),
        Facts(kind=IntentKind.SET_VENT_THRESHOLD, applied=False, rejection="no_value"),
        Facts(
            kind=IntentKind.SET_VENT_THRESHOLD,
            applied=False,
            rejection="out_of_range",
            channel_label="温度",
            unit="℃",
            value=300.0,
        ),
    ):
        assert numbers_are_grounded(render(facts), facts), facts.kind


def test_a_control_confirmation_states_the_setting_not_the_hardware() -> None:
    """The frame reaches the board on the next poll, and only if the
    application holds control of the device. Claiming the fan is already
    spinning would be a promise this layer cannot keep."""
    text = render(Facts(kind=IntentKind.FAN_ON, applied=True, fan_running=True))

    assert "手动常开" in text
    assert "已启动" not in text



def test_the_refusal_to_speak_states_the_limit_and_offers_the_alternative() -> None:
    """这句话不含任何数字，接地校验因此无从检查它——所以它不送模型改写，
    否则一次把"不支持手动播放"改成"可以试试"的润色会被原样采纳。"""
    text = render(Facts(kind=IntentKind.ANNOUNCE_REQUEST))

    assert text == ANNOUNCE_REFUSAL_TEXT
    assert "越限" in text
    assert "不支持手动播放" in text


def test_the_refusal_to_delete_says_where_the_data_is() -> None:
    """同样不含数字、同样不送改写：一次把"不在我能做的事情里"润色成
    "可以帮你清理"的改写，现有的每一道出口校验都拦不住——接地校验查的是数字。

    它把数据在哪三处说出来，而不是只说一个"删不了"：光说不行，
    换个说法再问一次就是最自然的下一步。"""
    text = render(Facts(kind=IntentKind.DELETE_REQUEST))

    assert text == DELETE_REFUSAL_TEXT
    assert "不在我能做的事情里" in text
    assert "清空历史记录" in text  # 说明那个按钮到底做什么
    assert not any(ch.isdigit() for ch in text)


def test_an_out_of_range_question_states_its_coverage_then_answers() -> None:
    """给出实际能给的那个值，但先说清它覆盖什么。问的人多半仍想知道这个数，
    连同"这不是昨天的"一起给出去，比一句干脆的拒绝有用；不能做的是不加标注
    直接给——那正是原先的行为。"""
    facts = Facts(
        kind=IntentKind.MAXIMUM,
        channel="noise",
        channel_label="噪声",
        unit="dB",
        value=49.5,
        maximum=49.5,
        past_scoped=True,
    )
    text = render(facts)

    assert text.startswith(phrasing_scope_notice())
    assert "49.5" in text


def phrasing_scope_notice() -> str:
    from service.assistant.phrasing import SCOPE_NOTICE

    return SCOPE_NOTICE


def test_a_rewording_may_not_add_a_verdict_the_template_lacked() -> None:
    """把"处于正常范围"从正常读数的模板里去掉之后，模板变短，模型反而更爱补话。
    30 次实测里补出来的分两类：纯废话（"请注意保暖"）和**没有依据的判断**
    （"目前该区域已恢复正常"）。后者才是要紧的——已有的黑名单只拦"事实未越限
    却声称越限"，"恢复正常""水平较高"都不在词表里，却同样是模型自己下的结论。"""
    calm = Facts(
        kind=IntentKind.CURRENT_VALUE,
        channel="noise",
        channel_label="噪声",
        unit="dB",
        value=49.5,
        triggered=False,
    )
    for reply in (
        "噪声 49.5dB。目前该区域已恢复正常。",
        "噪声 49.5dB，当前水平较高。",
        "噪声 49.5dB。数值正常。",
    ):
        text, source = choose("噪声现在是 49.5dB。", reply, calm)
        assert source is AnswerSource.TEMPLATE, reply
        assert text == "噪声现在是 49.5dB。"


def test_an_over_limit_reading_may_be_described_freely() -> None:
    """事实确实越限时不设这道限制：越限的读数用什么词形容都行。"""
    hot = Facts(
        kind=IntentKind.CURRENT_VALUE,
        channel="noise",
        channel_label="噪声",
        unit="dB",
        value=85.4,
        triggered=True,
    )
    text, source = choose(
        "噪声现在是 85.4dB，已超过报警阈值。", "噪声 85.4dB，已超标，情况异常。", hot
    )
    assert source is AnswerSource.MODEL


def test_advice_is_refused_by_name_not_by_length() -> None:
    """"请注意保暖"只比模板长八个字，任何宽到能容下正常改写的长度上限都拦不住它；
    为抓它去收紧上限，就是拿三十个样本去拟合。"""
    calm = Facts(
        kind=IntentKind.CURRENT_VALUE,
        channel="temperature",
        channel_label="温度",
        unit="℃",
        value=24.8,
        triggered=False,
    )
    _, source = choose(
        "温度现在是 24.8℃。", "现在的环境温度是 24.8℃，请注意保暖。", calm
    )
    assert source is AnswerSource.TEMPLATE


def test_the_length_cap_does_not_apply_to_the_explain_job() -> None:
    """长度上限是给改写档设的：改写的本职是换个说法，写长了就是加了东西。
    解释档的本职恰恰相反——把九项事实里模板丢掉的那些讲出来，必然更长。
    两者共用 choose()，不显式区分就会被自己的长度判死。

    这是 2026-09-09 加长度上限时引入的回归，由一次手工核对发现；
    测试没抓到，因为**没有任何用例拿真实长度的解释档输出走过 choose**。"""
    facts = Facts(
        kind=IntentKind.ALARM_STATE,
        channel="temperature",
        channel_label="温度",
        unit="℃",
        value=24.0,
        minimum=21.0,
        maximum=26.8,
        average=24.0,
        sample_count=120,
        threshold=35.0,
        threshold_high=35.0,
        triggered=False,
    )
    template = render(facts)
    expansion = (
        "当前温度为 24.0℃，在记录的最低值 21.0℃与最高值 26.8℃之间波动，"
        "共采集 120 个数据点。距离 35℃ 的报警阈值仍有余量，尚未越限。"
    )

    _, kept = choose(template, expansion, facts, expanded=True)
    assert kept is AnswerSource.MODEL

    _, capped = choose(template, expansion, facts, expanded=False)
    assert capped is AnswerSource.TEMPLATE


# -- 上云提议的三种答话（2026-09-18） -----------------------------------------


def test_a_pending_count_is_offered_with_the_number_in_the_facts() -> None:
    """数字必须登记进 Facts，否则模型改写会被接地校验整句退回——
    2026-09-08 的风扇模板正是这么踩的。这里连校验一起断言。"""
    facts = Facts(kind=IntentKind.CLOUD_SYNC_HINT, pending_uploads=12)

    text = render(facts)

    assert "12" in text
    assert numbers_are_grounded(text, facts)


def test_nothing_pending_still_offers_the_current_hour() -> None:
    """"没有待传的时段"曾经是一条死路（2026-09-18 到 09-21）。

    那句话准确，但用户问的是"现在的数据能传吗"，而当前这一小时确实还有
    读数没上去——只是归档按整点切，它还不算"待传"。按钮接上快照之后，
    这一档有事可做了，话必须跟着改，否则一句"没什么要传的"底下会坐着
    一个能传东西的按钮。

    仍然不含数字：当前这一小时有多少条要查历史库，而问答不查历史。"""
    text = render(Facts(kind=IntentKind.CLOUD_SYNC_HINT, pending_uploads=0))

    assert "已经结束的时段都传上去了" in text
    assert "当前这一小时" in text
    assert "点下面的按钮" in text
    assert not any(ch.isdigit() for ch in text)


def test_an_unreadable_ledger_does_not_guess_a_number() -> None:
    """这一档的整句价值就在那个数字上，编一个出来正是全系统在防的事。"""
    text = render(Facts(kind=IntentKind.CLOUD_SYNC_HINT, pending_uploads=None))

    assert "查不到" in text
    assert not any(ch.isdigit() for ch in text)


# -- 查看云端的答话（2026-09-19） ---------------------------------------------


def test_the_view_offer_says_plainly_that_it_only_reads() -> None:
    """用户看到一个跟"上传"长得差不多的按钮，第一反应是"点了会不会又传一遍"。
    把它不做什么写在按钮旁边，比事后解释省事。"""
    text = render(Facts(kind=IntentKind.CLOUD_VIEW_HINT))

    assert "只读" in text
    assert "不会上传" in text and "不会删除" not in text.replace("也不会删除", "")
    assert not any(ch.isdigit() for ch in text)


# -- judge(): choose() plus which check decided (2026-09-23) ------------------

_CALM_TEMP = Facts(
    kind=IntentKind.CURRENT_VALUE,
    channel="temperature",
    channel_label="温度",
    unit="℃",
    value=24.8,
    triggered=False,
)

_NOISE_T = "噪声现在是 76.3dB。"
_TEMP_T = "温度现在是 24.8℃。"
_V = CheckVerdict

_JUDGE_CASES = [
    # (template, model reply, facts, expanded, expected verdict)
    ("模板答案", None, _READING, False, _V.NO_REPLY),
    ("模板答案", "   ", _READING, False, _V.TOO_SHORT),
    ("模板答案", "噪声 99.9dB，快超标了。", _READING, False, _V.UNGROUNDED_NUMBER),
    (_NOISE_T, "噪声 76.3dB，已经超标。", _READING, False, _V.UNSUPPORTED_ALARM),
    (_TEMP_T, "温度 24.8℃。数值正常。", _CALM_TEMP, False, _V.UNSUPPORTED_JUDGEMENT),
    (_TEMP_T, "现在的环境温度是 24.8℃，请注意保暖。", _CALM_TEMP, False, _V.ADVICE),
    (_TEMP_T, "现在这里测得的温度是 24.8℃，这是刚刚采集到的数值，供参考。",
     _CALM_TEMP, False, _V.TOO_LONG),
    (_NOISE_T, "噪声 76.3dB。", _READING, False, _V.ACCEPTED),
]


def test_judge_agrees_with_choose_on_every_path() -> None:
    """choose() is judge() with the verdict dropped; the two must never
    disagree on the text or the source, or the web console would explain a
    decision the assistant did not make."""
    for template, reply, facts, expanded, _ in _JUDGE_CASES:
        text, source, _ = judge(template, reply, facts, expanded=expanded)
        expected = choose(template, reply, facts, expanded=expanded)
        assert (text, source) == expected, reply


def test_judge_names_the_check_that_decided() -> None:
    for template, reply, facts, expanded, verdict in _JUDGE_CASES:
        assert judge(template, reply, facts, expanded=expanded)[2] is verdict, reply

