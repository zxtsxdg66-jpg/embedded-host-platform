from device.sensors.channels import (
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from service.assistant.models import Intent, IntentKind
from service.assistant.retrieval import FactRetriever
from service.data_models import DataPoint
from service.sensor_data_processor import (
    HUMIDITY_ALARM_MAX,
    HUMIDITY_ALARM_MIN,
    NOISE_ALARM_MAX,
    SensorDataProcessor,
)
from service.ventilation_controller import FanMode, VentilationController


def _feed(
    processor: SensorDataProcessor, device: str, channel: str, *values: float
) -> None:
    for value in values:
        processor.handle_data_point(
            DataPoint(device_id=device, channel=channel, value=value)
        )


def _retriever(
    processor: SensorDataProcessor,
    devices: tuple[str, ...] = ("dev-1",),
    ventilation: VentilationController | None = None,
) -> FactRetriever:
    return FactRetriever(processor, lambda: list(devices), ventilation)


# -- readings and statistics --------------------------------------------------


def test_current_value_comes_from_the_processor() -> None:
    processor = SensorDataProcessor()
    _feed(processor, "dev-1", TEMPERATURE_CHANNEL, 20.0, 26.4)

    facts = _retriever(processor).retrieve(
        Intent(kind=IntentKind.CURRENT_VALUE, channel=TEMPERATURE_CHANNEL)
    )

    assert facts.available
    assert facts.value == 26.4
    assert facts.channel_label == "温度"
    assert facts.unit == "℃"


def test_statistics_are_carried_through() -> None:
    processor = SensorDataProcessor()
    _feed(processor, "dev-1", NOISE_CHANNEL, 60.0, 70.0, 80.0)

    facts = _retriever(processor).retrieve(
        Intent(kind=IntentKind.AVERAGE, channel=NOISE_CHANNEL)
    )

    assert facts.minimum == 60.0
    assert facts.maximum == 80.0
    assert facts.average == 70.0
    assert facts.sample_count == 3


def test_no_data_yields_unavailable_rather_than_an_error() -> None:
    """"There is no reading yet" is an ordinary answer, not a failure."""
    facts = _retriever(SensorDataProcessor()).retrieve(
        Intent(kind=IntentKind.CURRENT_VALUE, channel=HUMIDITY_CHANNEL)
    )

    assert not facts.available
    assert facts.value is None
    assert facts.channel_label == "湿度"


# -- multi-device aggregation -------------------------------------------------


def test_above_max_channel_reports_the_highest_device() -> None:
    """One over-threshold sensor is the condition that matters; averaging
    it away with compliant ones would hide it."""
    processor = SensorDataProcessor()
    _feed(processor, "dev-1", NOISE_CHANNEL, 50.0)
    _feed(processor, "dev-2", NOISE_CHANNEL, 85.0)

    facts = _retriever(processor, devices=("dev-1", "dev-2")).retrieve(
        Intent(kind=IntentKind.CURRENT_VALUE, channel=NOISE_CHANNEL)
    )

    assert facts.value == 85.0
    assert facts.triggered is True


def test_below_min_channel_reports_the_lowest_device() -> None:
    """Humidity's rule is BELOW_MIN, so "worst" is the smallest reading --
    always taking the maximum would answer the wrong way round."""
    processor = SensorDataProcessor()
    _feed(processor, "dev-1", HUMIDITY_CHANNEL, 75.0)
    _feed(processor, "dev-2", HUMIDITY_CHANNEL, 20.0)

    facts = _retriever(processor, devices=("dev-1", "dev-2")).retrieve(
        Intent(kind=IntentKind.CURRENT_VALUE, channel=HUMIDITY_CHANNEL)
    )

    assert facts.value == 20.0
    assert facts.triggered is True


def test_devices_without_data_are_skipped_not_fatal() -> None:
    processor = SensorDataProcessor()
    _feed(processor, "dev-2", NOISE_CHANNEL, 61.0)

    facts = _retriever(processor, devices=("dev-1", "dev-2", "dev-3")).retrieve(
        Intent(kind=IntentKind.CURRENT_VALUE, channel=NOISE_CHANNEL)
    )

    assert facts.available
    assert facts.value == 61.0


# -- thresholds ---------------------------------------------------------------


def test_threshold_facts_read_the_processors_own_constants() -> None:
    """No second copy of the numbers: the retriever imports the same
    public constants the processor evaluates against."""
    from service.sensor_data_processor import NOISE_ALARM_MAX

    facts = _retriever(SensorDataProcessor()).retrieve(
        Intent(kind=IntentKind.THRESHOLD_INFO, channel=NOISE_CHANNEL)
    )

    assert facts.threshold == NOISE_ALARM_MAX
    assert facts.threshold_is_maximum is True


def test_noise_threshold_carries_its_citation_and_others_do_not() -> None:
    retriever = _retriever(SensorDataProcessor())
    noise = retriever.retrieve(
        Intent(kind=IntentKind.THRESHOLD_INFO, channel=NOISE_CHANNEL)
    )
    temperature = retriever.retrieve(
        Intent(kind=IntentKind.THRESHOLD_INFO, channel=TEMPERATURE_CHANNEL)
    )

    assert "GB 37488" in noise.citation
    assert temperature.citation == ""


def test_humidity_reports_both_bounds_of_its_band() -> None:
    """Humidity gained a ceiling on 2026-09-08; stating only the floor
    would hide half of what raises an alarm."""
    facts = _retriever(SensorDataProcessor()).retrieve(
        Intent(kind=IntentKind.THRESHOLD_INFO, channel=HUMIDITY_CHANNEL)
    )

    assert facts.threshold_low == HUMIDITY_ALARM_MIN
    assert facts.threshold_high == HUMIDITY_ALARM_MAX


def test_a_single_bound_channel_leaves_the_other_side_empty() -> None:
    facts = _retriever(SensorDataProcessor()).retrieve(
        Intent(kind=IntentKind.THRESHOLD_INFO, channel=NOISE_CHANNEL)
    )

    assert facts.threshold_low is None
    assert facts.threshold_high == NOISE_ALARM_MAX


def test_damp_air_is_reported_against_the_ceiling_it_crossed() -> None:
    """The measured 62~78%RH of chapter 9 is what motivated the ceiling:
    the old one-sided rule called every one of those readings normal."""
    processor = SensorDataProcessor()
    _feed(processor, "dev-1", HUMIDITY_CHANNEL, 78.0)

    facts = _retriever(processor).retrieve(
        Intent(kind=IntentKind.ALARM_STATE, channel=HUMIDITY_CHANNEL)
    )

    assert facts.triggered is True
    assert facts.threshold == HUMIDITY_ALARM_MAX
    assert facts.threshold_is_maximum is True


def test_dry_air_is_still_reported_against_the_floor() -> None:
    processor = SensorDataProcessor()
    _feed(processor, "dev-1", HUMIDITY_CHANNEL, 21.0)

    facts = _retriever(processor).retrieve(
        Intent(kind=IntentKind.ALARM_STATE, channel=HUMIDITY_CHANNEL)
    )

    assert facts.triggered is True
    assert facts.threshold == HUMIDITY_ALARM_MIN
    assert facts.threshold_is_maximum is False


def test_a_normal_reading_quotes_the_bound_it_is_nearest() -> None:
    """Quoting an arbitrary side would tell a reader "62%RH, well above
    30%RH" while it sits three points under the ceiling."""
    processor = SensorDataProcessor()
    _feed(processor, "dev-1", HUMIDITY_CHANNEL, 62.0)

    facts = _retriever(processor).retrieve(
        Intent(kind=IntentKind.ALARM_STATE, channel=HUMIDITY_CHANNEL)
    )

    assert facts.triggered is False
    assert facts.threshold == HUMIDITY_ALARM_MAX


def test_the_device_furthest_outside_the_band_answers_for_the_channel() -> None:
    """Two devices, one dry and one damp: the worst reading is the one
    that matters, whichever side of the band it fell off."""
    processor = SensorDataProcessor()
    _feed(processor, "dev-a", HUMIDITY_CHANNEL, 50.0)
    _feed(processor, "dev-b", HUMIDITY_CHANNEL, 82.0)

    facts = _retriever(processor, devices=("dev-a", "dev-b")).retrieve(
        Intent(kind=IntentKind.ALARM_STATE, channel=HUMIDITY_CHANNEL)
    )

    assert facts.value == 82.0
    assert facts.triggered is True


# -- whole-system questions ---------------------------------------------------


def test_fan_facts_come_from_the_ventilation_controller() -> None:
    ventilation = VentilationController()
    ventilation.set_mode(FanMode.MANUAL_ON)

    facts = _retriever(SensorDataProcessor(), ventilation=ventilation).retrieve(
        Intent(kind=IntentKind.FAN_STATE)
    )

    assert facts.fan_running is True
    assert facts.fan_mode == "MANUAL_ON"


def test_fan_facts_unavailable_without_a_controller() -> None:
    facts = _retriever(SensorDataProcessor()).retrieve(
        Intent(kind=IntentKind.FAN_STATE)
    )
    assert not facts.available


def test_device_list_facts() -> None:
    facts = _retriever(SensorDataProcessor(), devices=("a", "b", "c")).retrieve(
        Intent(kind=IntentKind.DEVICE_LIST)
    )
    assert facts.device_ids == ("a", "b", "c")


def test_channel_question_without_a_channel_is_unavailable() -> None:
    """Answering for one arbitrary channel would be confidently wrong."""
    facts = _retriever(SensorDataProcessor()).retrieve(
        Intent(kind=IntentKind.ALARM_STATE, channel=None)
    )
    assert not facts.available
