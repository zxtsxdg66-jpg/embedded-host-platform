from random import Random

from device.interface import DeviceInterface
from device.sensors.channels import NOISE_CHANNEL
from device.sensors.noise import (
    NOISE_BASELINE_MAX,
    NOISE_BASELINE_MIN,
    NOISE_SPIKE_MAX,
    NoiseSensorSimulator,
)
from device.simulator import SimulatorDevice


def test_noise_sensor_is_a_simulator_device() -> None:
    sensor = NoiseSensorSimulator()
    assert isinstance(sensor, SimulatorDevice)
    assert isinstance(sensor, DeviceInterface)


def test_noise_sensor_default_device_id() -> None:
    sensor = NoiseSensorSimulator()
    assert sensor.device_id == "noise-sensor-1"


def test_noise_sensor_capability_declares_noise_channel() -> None:
    sensor = NoiseSensorSimulator()
    assert sensor.capability.has_channel(NOISE_CHANNEL)


def test_noise_sensor_generates_data_point() -> None:
    sensor = NoiseSensorSimulator(rng=Random(1))
    point = sensor.generate(NOISE_CHANNEL)

    assert point.device_id == sensor.device_id
    assert point.channel == NOISE_CHANNEL
    assert isinstance(point.value, float)


def test_noise_sensor_normal_readings_within_baseline() -> None:
    sensor = NoiseSensorSimulator(spike_probability=0.0, rng=Random(2))
    values = [sensor.generate(NOISE_CHANNEL).value for _ in range(100)]
    assert all(NOISE_BASELINE_MIN <= value <= NOISE_BASELINE_MAX for value in values)


def test_noise_sensor_produces_short_term_peaks() -> None:
    sensor = NoiseSensorSimulator(spike_probability=1.0, rng=Random(3))
    values = [sensor.generate(NOISE_CHANNEL).value for _ in range(50)]
    assert all(value > NOISE_BASELINE_MAX for value in values)
    assert any(value >= 80.0 for value in values)


def test_noise_sensor_default_mostly_produces_baseline_with_some_peaks() -> None:
    sensor = NoiseSensorSimulator(rng=Random(4))
    values = [sensor.generate(NOISE_CHANNEL).value for _ in range(500)]
    baseline_count = sum(1 for v in values if v <= NOISE_BASELINE_MAX)
    peak_count = sum(1 for v in values if v > NOISE_BASELINE_MAX)
    assert baseline_count > peak_count
    assert peak_count > 0
    assert max(values) <= NOISE_SPIKE_MAX
