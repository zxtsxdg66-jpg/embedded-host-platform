"""Instructions: what gets carried out, and what gets refused.

The interesting tests here are the refusals. Acting on a sentence is the
one place in this feature where being wrong has an effect rather than just
a wording, so the boundary is drawn by tests rather than by prose in a
prompt.
"""

from device.sensors.channels import (
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from service.assistant.control import (
    CONTROL_KINDS,
    REJECT_NO_CHANNEL,
    REJECT_NO_CONTROLLER,
    REJECT_NO_VALUE,
    REJECT_OUT_OF_RANGE,
    ControlExecutor,
    extract_value,
)
from service.assistant.models import Intent, IntentKind
from service.ventilation_controller import FanMode, VentilationController


def _executor() -> tuple[ControlExecutor, VentilationController]:
    ventilation = VentilationController()
    return ControlExecutor(ventilation), ventilation


def test_turning_the_fan_on_sets_a_manual_override() -> None:
    executor, ventilation = _executor()

    facts = executor.execute(Intent(kind=IntentKind.FAN_ON), "把风扇打开")

    assert facts.applied is True
    assert ventilation.settings.mode is FanMode.MANUAL_ON
    assert facts.fan_running is True


def test_turning_it_off_and_handing_it_back_are_the_same_write() -> None:
    """Not a separate control path: exactly the settings a click writes,
    so an instruction cannot reach the device by a route a click could
    not."""
    executor, ventilation = _executor()

    executor.execute(Intent(kind=IntentKind.FAN_OFF), "关掉风扇")
    assert ventilation.settings.mode is FanMode.MANUAL_OFF

    executor.execute(Intent(kind=IntentKind.FAN_AUTO), "风扇交给自动")
    assert ventilation.settings.mode is FanMode.AUTO


def test_a_threshold_moves_to_the_number_in_the_users_own_sentence() -> None:
    executor, ventilation = _executor()

    facts = executor.execute(
        Intent(kind=IntentKind.SET_VENT_THRESHOLD, channel=TEMPERATURE_CHANNEL),
        "把通风温度阈值调到 28 度",
    )

    assert facts.applied is True
    assert facts.threshold == 28.0
    assert ventilation.settings.temperature_max == 28.0


def test_the_other_threshold_is_left_alone() -> None:
    executor, ventilation = _executor()
    before = ventilation.settings.temperature_max

    executor.execute(
        Intent(kind=IntentKind.SET_VENT_THRESHOLD, channel=HUMIDITY_CHANNEL),
        "通风湿度阈值设成 75",
    )

    assert ventilation.settings.humidity_max == 75.0
    assert ventilation.settings.temperature_max == before


def test_an_out_of_range_value_is_refused_and_nothing_changes() -> None:
    """"调到 300 度" is not a demanding setting, it is an unreachable one:
    the sensor cannot report it, so the fan would simply never run."""
    executor, ventilation = _executor()
    before = ventilation.settings.temperature_max

    facts = executor.execute(
        Intent(kind=IntentKind.SET_VENT_THRESHOLD, channel=TEMPERATURE_CHANNEL),
        "通风温度阈值调到 300 度",
    )

    assert facts.applied is False
    assert facts.rejection == REJECT_OUT_OF_RANGE
    assert facts.value == 300.0  # quoted back, and grounded for the answer
    assert ventilation.settings.temperature_max == before


def test_a_sentence_with_no_number_is_refused() -> None:
    executor, ventilation = _executor()
    before = ventilation.settings.temperature_max

    facts = executor.execute(
        Intent(kind=IntentKind.SET_VENT_THRESHOLD, channel=TEMPERATURE_CHANNEL),
        "把通风温度阈值调低一点",
    )

    assert facts.applied is False
    assert facts.rejection == REJECT_NO_VALUE
    assert ventilation.settings.temperature_max == before


def test_two_numbers_are_refused_rather_than_guessed() -> None:
    """"从 30 调到 28" -- taking the first number would set the threshold to
    the value the user is moving away from."""
    executor, ventilation = _executor()
    before = ventilation.settings.temperature_max

    facts = executor.execute(
        Intent(kind=IntentKind.SET_VENT_THRESHOLD, channel=TEMPERATURE_CHANNEL),
        "把通风温度阈值从 30 调到 28",
    )

    assert facts.applied is False
    assert facts.rejection == REJECT_NO_VALUE
    assert ventilation.settings.temperature_max == before


def test_a_channel_that_cannot_be_ventilated_is_refused() -> None:
    """Noise has no ventilation threshold -- a fan does not reduce sound,
    it adds to it."""
    executor, _ = _executor()

    facts = executor.execute(
        Intent(kind=IntentKind.SET_VENT_THRESHOLD, channel=NOISE_CHANNEL),
        "通风噪声阈值调到 70",
    )

    assert facts.applied is False
    assert facts.rejection == REJECT_NO_CHANNEL


def test_without_a_ventilation_controller_nothing_is_attempted() -> None:
    facts = ControlExecutor(None).execute(Intent(kind=IntentKind.FAN_ON), "开风扇")

    assert facts.applied is False
    assert facts.rejection == REJECT_NO_CONTROLLER


def test_an_intent_outside_the_whitelist_cannot_act() -> None:
    """The whitelist is the routing rule *and* the last line of defence:
    a kind nobody added to it does nothing, which is the right default for
    a kind added later by someone reading only the enum."""
    executor, ventilation = _executor()
    before = ventilation.settings.mode

    facts = executor.execute(Intent(kind=IntentKind.CURRENT_VALUE), "现在温度多少")

    assert facts.applied is False
    assert ventilation.settings.mode is before


def test_the_whitelist_holds_exactly_the_four_reversible_actions() -> None:
    assert CONTROL_KINDS == {
        IntentKind.FAN_ON,
        IntentKind.FAN_OFF,
        IntentKind.FAN_AUTO,
        IntentKind.SET_VENT_THRESHOLD,
    }


def test_extract_value_reads_digits_only_from_the_text_given() -> None:
    assert extract_value("调到 28 度") == 28.0
    assert extract_value("设成 75.5") == 75.5
    assert extract_value("调低一点") is None
    assert extract_value("从 30 调到 28") is None
