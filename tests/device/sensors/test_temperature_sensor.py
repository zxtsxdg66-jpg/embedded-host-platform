from random import Random

from device.interface import DeviceInterface
from device.sensors.channels import TEMPERATURE_CHANNEL
from device.sensors.temperature import (
    TEMPERATURE_MAX,
    TEMPERATURE_MIN,
    TemperatureSensorSimulator,
)
from device.simulator import SimulatorDevice


def test_temperature_sensor_is_a_simulator_device() -> None:
    sensor = TemperatureSensorSimulator()
    assert isinstance(sensor, SimulatorDevice)
    assert isinstance(sensor, DeviceInterface)


def test_temperature_sensor_default_device_id() -> None:
    sensor = TemperatureSensorSimulator()
    assert sensor.device_id == "temperature-sensor-1"


def test_temperature_sensor_capability_declares_temperature_channel() -> None:
    sensor = TemperatureSensorSimulator()
    assert sensor.capability.has_channel(TEMPERATURE_CHANNEL)


def test_temperature_sensor_generates_data_point_in_range() -> None:
    sensor = TemperatureSensorSimulator(rng=Random(1))
    point = sensor.generate(TEMPERATURE_CHANNEL)

    assert point.device_id == sensor.device_id
    assert point.channel == TEMPERATURE_CHANNEL
    assert isinstance(point.value, float)
    assert TEMPERATURE_MIN <= point.value <= TEMPERATURE_MAX


def test_temperature_sensor_stays_within_range_over_many_samples() -> None:
    sensor = TemperatureSensorSimulator(rng=Random(2))
    values = [sensor.generate(TEMPERATURE_CHANNEL).value for _ in range(500)]
    assert all(TEMPERATURE_MIN <= value <= TEMPERATURE_MAX for value in values)


def test_temperature_sensor_changes_smoothly() -> None:
    max_step = 0.3
    sensor = TemperatureSensorSimulator(max_step=max_step, rng=Random(3))
    values = [sensor.generate(TEMPERATURE_CHANNEL).value for _ in range(100)]
    deltas = [abs(b - a) for a, b in zip(values, values[1:], strict=False)]
    assert all(delta <= max_step + 1e-9 for delta in deltas)
