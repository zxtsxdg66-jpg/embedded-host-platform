import pytest

from service.alarm_announcer import (
    DEFAULT_CONFIRM_CYCLES,
    DEFAULT_COOLDOWN_SECONDS,
    AlarmAnnouncer,
    AlertKind,
    AnnouncementRequest,
)
from service.sensor_data_processor import AlarmKind, ThresholdStatus


class _FakeClock:
    """Monotonic millisecond clock a test can advance by hand."""

    def __init__(self) -> None:
        self.now_ms = 0

    def __call__(self) -> int:
        return self.now_ms

    def advance_seconds(self, seconds: float) -> None:
        self.now_ms += int(seconds * 1000)


def _status(
    channel: str = "temperature",
    triggered: bool = True,
    device_id: str = "mcu-1",
    kind: AlarmKind = AlarmKind.ABOVE_MAX,
) -> ThresholdStatus:
    return ThresholdStatus(
        device_id=device_id,
        channel=channel,
        value=99.0,
        threshold=35.0,
        kind=kind,
        triggered=triggered,
    )


def _announcer(
    clock: _FakeClock | None = None, **kwargs: object
) -> tuple[AlarmAnnouncer, list[AnnouncementRequest]]:
    """默认显式给 ``confirm_cycles=2``。

    2026-09-09 之后本类的默认值是 1——连续确认已下沉到 SensorDataProcessor，
    生产链路上播报器拿到的 triggered 早已是确认过的。但**确认机制本身仍在这里**
    （参数还在，串联时可叠加），下面这几个用例测的正是它，所以显式要 2；
    默认值本身另有一个用例专门盯着。
    """
    clock = clock or _FakeClock()
    kwargs.setdefault("confirm_cycles", 2)
    announcer = AlarmAnnouncer(clock_ms=clock, **kwargs)  # type: ignore[arg-type]
    seen: list[AnnouncementRequest] = []
    announcer.on_announcement(seen.append)
    return announcer, seen


# -- construction -------------------------------------------------------------


def test_defaults_match_the_agreed_values() -> None:
    """确认次数的默认值 2026-09-09 由 2 改为 1：同一条规则下沉到了
    SensorDataProcessor，好让界面高亮、LCD 位图与语音三者对"什么算报警"
    看法一致。留在 1 而非删掉，是因为本类的连续计数还担着另一半职责——
    一次越限只播报一遍，而不是每个读数都播。"""
    assert DEFAULT_CONFIRM_CYCLES == 1
    assert DEFAULT_COOLDOWN_SECONDS == 30.0


def test_a_flip_to_the_other_side_of_the_band_starts_a_new_streak() -> None:
    """Humidity has had two bounds since 2026-09-08. Air that drifts from
    too dry to too damp is a new excursion, and it has to earn its own
    confirmation rather than inherit the previous one's count."""
    announcer, seen = _announcer()

    announcer.handle_threshold_status(_status("humidity", kind=AlarmKind.BELOW_MIN))
    announcer.handle_threshold_status(_status("humidity", kind=AlarmKind.ABOVE_MAX))

    assert seen == []

    announcer.handle_threshold_status(_status("humidity", kind=AlarmKind.ABOVE_MAX))

    assert len(seen) == 1


@pytest.mark.parametrize("cycles", [0, -1])
def test_confirm_cycles_below_one_is_rejected(cycles: int) -> None:
    with pytest.raises(ValueError):
        AlarmAnnouncer(confirm_cycles=cycles)


def test_negative_cooldown_is_rejected() -> None:
    with pytest.raises(ValueError):
        AlarmAnnouncer(cooldown_seconds=-1.0)


# -- consecutive confirmation -------------------------------------------------


def test_single_spike_does_not_announce() -> None:
    """A door slamming near the noise sensor must not make it talk."""
    announcer, seen = _announcer()

    announcer.handle_threshold_status(_status(channel="noise"))

    assert seen == []


def test_two_consecutive_readings_announce() -> None:
    announcer, seen = _announcer()

    announcer.handle_threshold_status(_status())
    announcer.handle_threshold_status(_status())

    assert len(seen) == 1
    assert seen[0].kind is AlertKind.TEMPERATURE


def test_a_normal_reading_resets_the_streak() -> None:
    announcer, seen = _announcer()

    announcer.handle_threshold_status(_status())
    announcer.handle_threshold_status(_status(triggered=False))
    announcer.handle_threshold_status(_status())

    assert seen == []


def test_ongoing_excursion_announces_only_once() -> None:
    """A sustained alarm must not re-announce on every 3 s reading."""
    announcer, seen = _announcer()

    for _ in range(10):
        announcer.handle_threshold_status(_status())

    assert len(seen) == 1


def test_confirm_cycles_is_configurable() -> None:
    announcer, seen = _announcer(confirm_cycles=3)

    announcer.handle_threshold_status(_status())
    announcer.handle_threshold_status(_status())
    assert seen == []

    announcer.handle_threshold_status(_status())
    assert len(seen) == 1


def test_streaks_are_tracked_per_device_and_channel() -> None:
    announcer, seen = _announcer()

    announcer.handle_threshold_status(_status(channel="temperature"))
    announcer.handle_threshold_status(_status(channel="noise"))

    assert seen == []


# -- channel mapping ----------------------------------------------------------


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        ("temperature", AlertKind.TEMPERATURE),
        ("humidity", AlertKind.HUMIDITY),
        ("noise", AlertKind.NOISE),
    ],
)
def test_each_channel_maps_to_its_phrase(channel: str, expected: AlertKind) -> None:
    announcer, seen = _announcer()

    announcer.handle_threshold_status(_status(channel=channel))
    announcer.handle_threshold_status(_status(channel=channel))

    assert seen[0].kind is expected


def test_unknown_channel_never_announces() -> None:
    announcer, seen = _announcer()

    for _ in range(5):
        announcer.handle_threshold_status(_status(channel="pressure"))

    assert seen == []


def test_alert_kind_value_is_the_wire_command_name() -> None:
    """Keeps the phrase -> device command mapping in one place."""
    assert AlertKind.TEMPERATURE.value == "ALERT_TEMPERATURE"
    assert AlertKind.HUMIDITY.value == "ALERT_HUMIDITY"
    assert AlertKind.NOISE.value == "ALERT_NOISE"


# -- cooldown -----------------------------------------------------------------


def test_second_alarm_within_cooldown_is_suppressed() -> None:
    clock = _FakeClock()
    announcer, seen = _announcer(clock)

    for _ in range(2):
        announcer.handle_threshold_status(_status(channel="temperature"))
    clock.advance_seconds(5.0)
    for _ in range(2):
        announcer.handle_threshold_status(_status(channel="noise"))

    assert len(seen) == 1
    assert announcer.suppressed_count == 1


def test_cooldown_is_global_across_channels() -> None:
    """One speaker: a queue of announcements from three channels is
    exactly the runaway the cooldown exists to prevent."""
    clock = _FakeClock()
    announcer, seen = _announcer(clock)

    for channel in ("temperature", "humidity", "noise"):
        for _ in range(2):
            announcer.handle_threshold_status(_status(channel=channel))

    assert len(seen) == 1
    assert announcer.suppressed_count == 2


def test_announcement_allowed_again_after_cooldown_expires() -> None:
    clock = _FakeClock()
    announcer, seen = _announcer(clock)
    for _ in range(2):
        announcer.handle_threshold_status(_status(channel="temperature"))

    clock.advance_seconds(DEFAULT_COOLDOWN_SECONDS + 0.1)
    for _ in range(2):
        announcer.handle_threshold_status(_status(channel="noise"))

    assert len(seen) == 2
    assert seen[1].kind is AlertKind.NOISE


def test_cooldown_active_reflects_state() -> None:
    clock = _FakeClock()
    announcer, _ = _announcer(clock)
    assert announcer.cooldown_active is False

    for _ in range(2):
        announcer.handle_threshold_status(_status())
    assert announcer.cooldown_active is True

    clock.advance_seconds(DEFAULT_COOLDOWN_SECONDS + 0.1)
    assert announcer.cooldown_active is False


def test_suppressed_announcement_does_not_extend_the_cooldown() -> None:
    """A suppressed attempt must not restart the timer, or a busy site
    would never speak again."""
    clock = _FakeClock()
    announcer, seen = _announcer(clock)
    for _ in range(2):
        announcer.handle_threshold_status(_status(channel="temperature"))

    clock.advance_seconds(29.0)
    for _ in range(2):
        announcer.handle_threshold_status(_status(channel="humidity"))
    clock.advance_seconds(1.5)
    for _ in range(2):
        announcer.handle_threshold_status(_status(channel="noise"))

    assert len(seen) == 2


def test_zero_cooldown_allows_back_to_back_announcements() -> None:
    announcer, seen = _announcer(cooldown_seconds=0.0)

    for channel in ("temperature", "noise"):
        for _ in range(2):
            announcer.handle_threshold_status(_status(channel=channel))

    assert len(seen) == 2
