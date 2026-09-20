import pytest

from api.exceptions import (
    CommandAuthorityError,
    CommandNotFoundError,
    DeviceNotFoundError,
)
from api.local_api import LocalApi
from application.runtime import ApplicationRuntime, DeviceStatusView
from communication.loopback import LoopbackChannel
from device.simulator import ConstantValueGenerator, SimulatedChannel, SimulatorDevice
from service.command_models import Command, CommandStatus
from service.data_models import DataPoint


def _make_api(
    device_id: str = "sim-1", accepted_commands: tuple[str, ...] = ("PING",)
) -> LocalApi:
    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id=device_id,
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(1))
        ],
    )
    runtime.register_device(
        device, LoopbackChannel(), accepted_commands=accepted_commands
    )
    return LocalApi(runtime)


def test_local_api_satisfies_api_interface() -> None:
    from api.interface import ApiInterface

    api = _make_api()
    assert isinstance(api, ApiInterface)


# ---------------------------------------------------------------------------
# 1. 查询设备列表
# ---------------------------------------------------------------------------


def test_list_devices_returns_registered_ids() -> None:
    api = _make_api(device_id="sim-1")
    assert api.list_devices() == ["sim-1"]


def test_list_devices_empty_when_none_registered() -> None:
    api = LocalApi(ApplicationRuntime())
    assert api.list_devices() == []


# ---------------------------------------------------------------------------
# 2. 查询设备状态
# ---------------------------------------------------------------------------


def test_get_device_status_returns_status_view() -> None:
    api = _make_api(device_id="sim-1")
    status = api.get_device_status("sim-1")
    assert isinstance(status, DeviceStatusView)
    assert status.device_id == "sim-1"
    assert status.is_connected is True
    assert status.is_occupied is False
    assert status.occupant is None


def test_get_device_status_reflects_occupancy() -> None:
    api = _make_api(device_id="sim-1")
    api.acquire_control("sim-1", "client-1")
    status = api.get_device_status("sim-1")
    assert status.is_occupied is True
    assert status.occupant == "client-1"


def test_get_device_status_unknown_device_raises_device_not_found() -> None:
    api = _make_api()
    with pytest.raises(DeviceNotFoundError):
        api.get_device_status("unknown")


# ---------------------------------------------------------------------------
# 3. 数据订阅
# ---------------------------------------------------------------------------


def test_subscribe_data_receives_published_points() -> None:
    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id="sim-1",
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(7))
        ],
    )
    runtime.register_device(device, LoopbackChannel())
    api = LocalApi(runtime)

    received: list[DataPoint] = []
    api.subscribe_data("sim-1", "ch1", received.append)

    published = runtime.report_data("sim-1", "ch1")

    assert received == [published]


def test_unsubscribe_data_stops_delivery() -> None:
    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id="sim-1",
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(7))
        ],
    )
    runtime.register_device(device, LoopbackChannel())
    api = LocalApi(runtime)

    received: list[DataPoint] = []
    subscription_id = api.subscribe_data("sim-1", "ch1", received.append)
    api.unsubscribe_data(subscription_id)

    runtime.report_data("sim-1", "ch1")

    assert received == []


# ---------------------------------------------------------------------------
# 4. 提交控制命令（含控制权获取/释放）
# ---------------------------------------------------------------------------


def test_acquire_control_grants_exclusive_authority() -> None:
    api = _make_api()
    assert api.acquire_control("sim-1", "client-1") is True
    assert api.acquire_control("sim-1", "client-2") is False


def test_release_control_frees_device_for_other_clients() -> None:
    api = _make_api()
    api.acquire_control("sim-1", "client-1")
    api.release_control("sim-1", "client-1")
    assert api.acquire_control("sim-1", "client-2") is True


def test_submit_command_succeeds_for_accepted_command() -> None:
    api = _make_api(accepted_commands=("PING",))
    api.acquire_control("sim-1", "client-1")

    result = api.submit_command(
        Command(device_id="sim-1", command_type="PING", origin="client-1")
    )

    assert result.status is CommandStatus.SUCCESS


def test_submit_command_fails_for_unaccepted_command() -> None:
    api = _make_api(accepted_commands=("PING",))
    api.acquire_control("sim-1", "client-1")

    result = api.submit_command(
        Command(device_id="sim-1", command_type="UNKNOWN", origin="client-1")
    )

    assert result.status is CommandStatus.FAILED


def test_submit_command_without_acquiring_raises_command_authority_error() -> None:
    api = _make_api()
    with pytest.raises(CommandAuthorityError):
        api.submit_command(
            Command(device_id="sim-1", command_type="PING", origin="client-1")
        )


def test_submit_command_by_non_owning_client_raises_command_authority_error() -> None:
    api = _make_api()
    api.acquire_control("sim-1", "client-1")
    with pytest.raises(CommandAuthorityError):
        api.submit_command(
            Command(device_id="sim-1", command_type="PING", origin="client-2")
        )


def test_submit_command_for_unknown_device_raises_device_not_found() -> None:
    api = _make_api()
    # Occupancy bookkeeping does not itself validate device existence, so
    # acquiring succeeds; the NotFoundError surfaces once dispatch actually
    # tries to reach the (unregistered) device.
    api.acquire_control("unknown", "client-1")
    with pytest.raises(DeviceNotFoundError):
        api.submit_command(
            Command(device_id="unknown", command_type="PING", origin="client-1")
        )


# ---------------------------------------------------------------------------
# 5. 查询命令结果
# ---------------------------------------------------------------------------


def test_get_command_result_matches_submit_result() -> None:
    api = _make_api()
    api.acquire_control("sim-1", "client-1")
    command = Command(device_id="sim-1", command_type="PING", origin="client-1")

    submitted = api.submit_command(command)
    fetched = api.get_command_result(command.command_id)

    assert fetched == submitted


def test_get_command_result_unknown_id_raises_command_not_found() -> None:
    api = _make_api()
    with pytest.raises(CommandNotFoundError):
        api.get_command_result("no-such-command")


# ---------------------------------------------------------------------------
# 6. 阈值报警状态订阅
# ---------------------------------------------------------------------------


def _make_temperature_runtime_and_api(
    value: float, device_id: str = "sim-1"
) -> tuple[ApplicationRuntime, LocalApi]:
    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id=device_id,
        channels=[
            SimulatedChannel(
                channel_id="temperature", generator=ConstantValueGenerator(value)
            )
        ],
    )
    runtime.register_device(device, LoopbackChannel())
    return runtime, LocalApi(runtime)


def test_subscribe_alarm_status_fires_with_triggered_true_on_violation() -> None:
    from service.sensor_data_processor import TEMPERATURE_ALARM_MAX, ThresholdStatus

    runtime, api = _make_temperature_runtime_and_api(TEMPERATURE_ALARM_MAX + 5)
    statuses: list[ThresholdStatus] = []
    api.subscribe_alarm_status(statuses.append)

    # 两次：2026-09-09 起报警需连续确认，一次越限只是嫌疑。
    runtime.report_data("sim-1", "temperature")
    runtime.report_data("sim-1", "temperature")

    assert len(statuses) == 2
    assert [s.triggered for s in statuses] == [False, True]
    assert statuses[0].device_id == "sim-1"
    assert statuses[0].channel == "temperature"


def test_subscribe_alarm_status_fires_with_triggered_false_for_normal_value() -> None:
    from service.sensor_data_processor import ThresholdStatus

    runtime, api = _make_temperature_runtime_and_api(20.0)
    statuses: list[ThresholdStatus] = []
    api.subscribe_alarm_status(statuses.append)

    runtime.report_data("sim-1", "temperature")

    assert len(statuses) == 1
    assert statuses[0].triggered is False


def test_subscribe_alarm_status_does_not_require_a_ui_data_subscription() -> None:
    """Alarm evaluation is independent of whether a client has separately
    called subscribe_data for that channel -- register_device() alone
    wires it up (see application/runtime.py's register_device docstring)."""
    from service.sensor_data_processor import TEMPERATURE_ALARM_MAX, ThresholdStatus

    runtime, api = _make_temperature_runtime_and_api(TEMPERATURE_ALARM_MAX + 5)
    statuses: list[ThresholdStatus] = []
    api.subscribe_alarm_status(statuses.append)
    # deliberately never call api.subscribe_data(...)

    runtime.report_data("sim-1", "temperature")

    assert len(statuses) == 1


# ---------------------------------------------------------------------------
# 7. 统计信息订阅
# ---------------------------------------------------------------------------


def test_subscribe_statistics_receives_running_snapshot() -> None:
    from service.sensor_data_processor import ChannelStatistics

    runtime, api = _make_temperature_runtime_and_api(20.0)
    seen: list[ChannelStatistics] = []
    api.subscribe_statistics(lambda _d, _c, stats: seen.append(stats))

    runtime.report_data("sim-1", "temperature")
    runtime.report_data("sim-1", "temperature")

    assert len(seen) == 2
    assert seen[-1].sample_count == 2
    assert seen[-1].current == 20.0


def test_subscribe_statistics_fires_for_channels_without_a_threshold_rule() -> None:
    from service.sensor_data_processor import ChannelStatistics

    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id="sim-1",
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(7))
        ],
    )
    runtime.register_device(device, LoopbackChannel())
    api = LocalApi(runtime)

    seen: list[ChannelStatistics] = []
    api.subscribe_statistics(lambda _d, _c, stats: seen.append(stats))

    runtime.report_data("sim-1", "ch1")

    assert len(seen) == 1
    assert seen[0].current == 7


# ---------------------------------------------------------------------------
# 8. 通风控制（2026-09-07 新增，扩展 ApiInterface 已获授权）
# ---------------------------------------------------------------------------


def test_get_ventilation_settings_exposes_defaults() -> None:
    from service.ventilation_controller import (
        DEFAULT_HUMIDITY_VENTILATION_MAX,
        DEFAULT_TEMPERATURE_VENTILATION_MAX,
        FanMode,
    )

    api = _make_api()

    settings = api.get_ventilation_settings()
    assert settings.temperature_max == DEFAULT_TEMPERATURE_VENTILATION_MAX
    assert settings.humidity_max == DEFAULT_HUMIDITY_VENTILATION_MAX
    assert settings.mode is FanMode.AUTO


def test_set_ventilation_thresholds_is_readable_back() -> None:
    api = _make_api()

    api.set_ventilation_thresholds(temperature_max=26.0, humidity_max=70.0)

    settings = api.get_ventilation_settings()
    assert settings.temperature_max == 26.0
    assert settings.humidity_max == 70.0


def test_set_ventilation_thresholds_leaves_omitted_value_alone() -> None:
    api = _make_api()
    original_humidity = api.get_ventilation_settings().humidity_max

    api.set_ventilation_thresholds(temperature_max=26.0)

    assert api.get_ventilation_settings().humidity_max == original_humidity


def test_set_fan_mode_is_readable_back() -> None:
    from service.ventilation_controller import FanMode

    api = _make_api()

    api.set_fan_mode(FanMode.MANUAL_ON)

    assert api.get_ventilation_settings().mode is FanMode.MANUAL_ON


def test_subscribe_fan_decision_receives_mode_changes() -> None:
    from service.ventilation_controller import FanDecision, FanMode

    api = _make_api()
    seen: list[FanDecision] = []
    api.subscribe_fan_decision(seen.append)

    api.set_fan_mode(FanMode.MANUAL_ON)

    assert len(seen) == 1
    assert seen[0].should_run is True


def test_ventilation_thresholds_do_not_alter_alarm_thresholds() -> None:
    """The GB 37488-2019-argued alarm limits must stay put when the
    runtime-adjustable ventilation limits move."""
    from service.sensor_data_processor import TEMPERATURE_ALARM_MAX

    api = _make_api()
    before = TEMPERATURE_ALARM_MAX

    api.set_ventilation_thresholds(temperature_max=10.0)

    from service.sensor_data_processor import TEMPERATURE_ALARM_MAX as after

    assert after == before


# ---------------------------------------------------------------------------
# 10. 历史读数查询（2026-09-17 新增）
# ---------------------------------------------------------------------------


def _api_with_history() -> tuple[LocalApi, ApplicationRuntime]:
    """挂上内存存储的 api。

    不落盘：这一层要验的是门面转调与空值语义，不是 SQLite 的行为，
    那些在 tests/storage/ 里单独验过。
    """
    from service.history import InMemoryHistoryStore

    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id="sim-1",
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(1))
        ],
    )
    runtime.register_device(device, LoopbackChannel(), accepted_commands=("PING",))
    runtime.attach_history(InMemoryHistoryStore())
    return LocalApi(runtime), runtime


def test_query_history_without_a_store_returns_nothing() -> None:
    """没挂存储时是空列表，不是异常。

    默认的 NullHistoryStore 让呈现端在任何装配下都能画出"暂无数据"，
    而不必先判断平台有没有持久化能力。
    """
    api = _make_api()

    assert api.query_history("sim-1", "ch1") == []


def test_query_history_returns_what_was_recorded() -> None:
    api, runtime = _api_with_history()

    runtime.report_data("sim-1", "ch1")
    runtime.history_recorder.flush()

    assert [point.value for point in api.query_history("sim-1", "ch1")] == [1.0]


def test_query_history_for_an_unknown_device_is_empty_not_an_error() -> None:
    """与 get_device_status 刻意相反。

    问一个不存在的设备的状态是调用方写错了；问它的历史则是呈现端
    在确认"这儿有没有数据"——空列表就是答案，不该逼调用方 catch。
    """
    api, _ = _api_with_history()

    assert api.query_history("sim-absent", "ch1") == []


def test_query_history_for_an_unknown_channel_is_empty() -> None:
    api, runtime = _api_with_history()
    runtime.report_data("sim-1", "ch1")
    runtime.history_recorder.flush()

    assert api.query_history("sim-1", "ch-absent") == []


def test_query_history_passes_the_limit_through() -> None:
    api, runtime = _api_with_history()
    for _ in range(5):
        runtime.report_data("sim-1", "ch1")
    runtime.history_recorder.flush()

    assert len(api.query_history("sim-1", "ch1", limit=2)) == 2


def test_query_history_passes_the_time_range_through() -> None:
    from datetime import datetime, timezone

    api, runtime = _api_with_history()
    runtime.report_data("sim-1", "ch1")
    runtime.history_recorder.flush()

    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    assert api.query_history("sim-1", "ch1", start=future) == []
