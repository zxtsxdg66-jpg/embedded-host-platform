"""Integration test for the "传感器应用模拟验证阶段" data flow:

    SensorSimulator -> DataService -> SensorDataProcessor

using the three environmental sensor SimulatorDevice presets
(TemperatureSensorSimulator/HumiditySensorSimulator/NoiseSensorSimulator).
Also verifies the same sensors work unmodified through the full existing
ApplicationRuntime/Protocol/Communication stack, proving no architecture
change was needed anywhere below the new src/device/sensors/ and
src/service/sensor_data_processor.py files.
"""

from __future__ import annotations

from random import Random

from application.runtime import ApplicationRuntime
from communication.loopback import LoopbackChannel
from device.sensors import (
    HumiditySensorSimulator,
    NoiseSensorSimulator,
    TemperatureSensorSimulator,
)
from device.sensors.channels import HUMIDITY_CHANNEL, NOISE_CHANNEL, TEMPERATURE_CHANNEL
from service.data_models import DataPoint
from service.data_service_impl import InMemoryDataService
from service.sensor_data_processor import AlarmEvent, SensorDataProcessor


def test_three_sensors_feed_one_processor_via_data_service() -> None:
    data_service = InMemoryDataService()
    processor = SensorDataProcessor(confirm_cycles=1)

    temperature = TemperatureSensorSimulator(rng=Random(1))
    humidity = HumiditySensorSimulator(rng=Random(2))
    noise = NoiseSensorSimulator(rng=Random(3))

    for sensor, channel in (
        (temperature, TEMPERATURE_CHANNEL),
        (humidity, HUMIDITY_CHANNEL),
        (noise, NOISE_CHANNEL),
    ):
        processor.subscribe_to(data_service, sensor.device_id, channel)
        data_service.publish(sensor.generate(channel))

    assert processor.get_statistics(
        temperature.device_id, TEMPERATURE_CHANNEL
    ).sample_count == 1
    assert processor.get_statistics(
        humidity.device_id, HUMIDITY_CHANNEL
    ).sample_count == 1
    assert processor.get_statistics(noise.device_id, NOISE_CHANNEL).sample_count == 1


def test_repeated_reports_build_up_meaningful_statistics() -> None:
    data_service = InMemoryDataService()
    processor = SensorDataProcessor(confirm_cycles=1)
    temperature = TemperatureSensorSimulator(max_step=1.0, rng=Random(4))
    processor.subscribe_to(data_service, temperature.device_id, TEMPERATURE_CHANNEL)

    for _ in range(20):
        data_service.publish(temperature.generate(TEMPERATURE_CHANNEL))

    stats = processor.get_statistics(temperature.device_id, TEMPERATURE_CHANNEL)
    assert stats.sample_count == 20
    assert stats.minimum <= stats.average <= stats.maximum


def test_high_spike_probability_noise_sensor_eventually_raises_alarm() -> None:
    data_service = InMemoryDataService()
    processor = SensorDataProcessor(confirm_cycles=1)
    events: list[AlarmEvent] = []
    processor.on_alarm(events.append)

    noise = NoiseSensorSimulator(spike_probability=1.0, rng=Random(5))
    processor.subscribe_to(data_service, noise.device_id, NOISE_CHANNEL)

    data_service.publish(noise.generate(NOISE_CHANNEL))

    assert len(events) == 1
    assert events[0].channel == NOISE_CHANNEL


def test_sensors_work_unmodified_through_full_application_runtime_stack() -> None:
    """Proves no change was needed to application/protocol/communication/api/ui
    for these new device.sensors presets -- they are ordinary SimulatorDevice
    instances as far as the rest of the stack is concerned."""
    runtime = ApplicationRuntime()
    temperature = TemperatureSensorSimulator(rng=Random(6))
    runtime.register_device(temperature, LoopbackChannel())

    processor = SensorDataProcessor(confirm_cycles=1)
    runtime.subscribe(
        temperature.device_id, TEMPERATURE_CHANNEL, processor.handle_data_point
    )

    point = runtime.report_data(temperature.device_id, TEMPERATURE_CHANNEL)

    stats = processor.get_statistics(temperature.device_id, TEMPERATURE_CHANNEL)
    assert stats.current == point.value


def test_a_lone_spike_reaches_neither_the_screen_nor_the_speaker() -> None:
    """三个消费方对"什么算报警"看法一致——这条端到端串起来验。

    2026-09-09 之前：ThresholdStatus.triggered 逐点算出，界面高亮与
    AlarmStateDispatcher（0x15 → LCD 位图）立刻响应，而 AlarmAnnouncer 要连续
    两次才播报。单点尖峰因此让屏幕和 LCD 闪一下，语音全程没动静。
    确认下沉之后，同一个尖峰对三方都不成立。

    数值取自实测：长时间稳定性两次跑各有一个孤立点越过 80 dB
    （96.2 与 84.7），均为噪声传感器首帧伪值。
    """
    from service.alarm_announcer import AlarmAnnouncer

    processor = SensorDataProcessor()
    announced: list[object] = []
    announcer = AlarmAnnouncer()
    announcer.on_announcement(announced.append)
    processor.on_status(announcer.handle_threshold_status)

    alarms: list[object] = []
    processor.on_alarm(alarms.append)
    statuses: list[bool] = []
    processor.on_status(lambda s: statuses.append(s.triggered))

    for value in (40.1, 96.2, 40.0, 39.7):
        processor.handle_data_point(
            DataPoint(device_id="dev-1", channel="noise", value=value)
        )

    assert announced == []          # 语音：不响
    assert alarms == []             # 活动日志：不记
    assert statuses == [False] * 4  # 界面与 LCD：不亮


def test_a_sustained_excursion_reaches_all_three() -> None:
    """反过来：真正持续的越限，三方都要动。"""
    from service.alarm_announcer import AlarmAnnouncer

    processor = SensorDataProcessor()
    announced: list[object] = []
    announcer = AlarmAnnouncer()
    announcer.on_announcement(announced.append)
    processor.on_status(announcer.handle_threshold_status)

    alarms: list[object] = []
    processor.on_alarm(alarms.append)
    statuses: list[bool] = []
    processor.on_status(lambda s: statuses.append(s.triggered))

    for value in (85.0, 86.0, 87.0):
        processor.handle_data_point(
            DataPoint(device_id="dev-1", channel="noise", value=value)
        )

    assert len(announced) == 1              # 一次越限只播一遍
    assert len(alarms) == 2                 # 确认后的每个读数都是一次事件
    assert statuses == [False, True, True]
