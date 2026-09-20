from random import Random

from device.interface import DeviceInterface
from device.sensors.channels import HUMIDITY_CHANNEL
from device.sensors.humidity import HUMIDITY_MAX, HUMIDITY_MIN, HumiditySensorSimulator
from device.simulator import SimulatorDevice


def test_humidity_sensor_is_a_simulator_device() -> None:
    sensor = HumiditySensorSimulator()
    assert isinstance(sensor, SimulatorDevice)
    assert isinstance(sensor, DeviceInterface)


def test_humidity_sensor_default_device_id() -> None:
    sensor = HumiditySensorSimulator()
    assert sensor.device_id == "humidity-sensor-1"


def test_humidity_sensor_capability_declares_humidity_channel() -> None:
    sensor = HumiditySensorSimulator()
    assert sensor.capability.has_channel(HUMIDITY_CHANNEL)


def test_humidity_sensor_generates_data_point_in_range() -> None:
    sensor = HumiditySensorSimulator(rng=Random(1))
    point = sensor.generate(HUMIDITY_CHANNEL)

    assert point.device_id == sensor.device_id
    assert point.channel == HUMIDITY_CHANNEL
    assert isinstance(point.value, float)
    assert HUMIDITY_MIN <= point.value <= HUMIDITY_MAX


def test_humidity_sensor_stays_within_range_over_many_samples() -> None:
    sensor = HumiditySensorSimulator(rng=Random(2))
    values = [sensor.generate(HUMIDITY_CHANNEL).value for _ in range(500)]
    assert all(HUMIDITY_MIN <= value <= HUMIDITY_MAX for value in values)


def test_humidity_sensor_changes_slowly() -> None:
    """Humidity's default max_step must be smaller than temperature's, per
    the "变化缓慢" requirement -- verified by comparing achievable deltas."""
    max_step = 0.15
    sensor = HumiditySensorSimulator(max_step=max_step, rng=Random(3))
    values = [sensor.generate(HUMIDITY_CHANNEL).value for _ in range(100)]
    deltas = [abs(b - a) for a, b in zip(values, values[1:], strict=False)]
    assert all(delta <= max_step + 1e-9 for delta in deltas)


def test_humidity_default_max_step_is_smaller_than_temperature_default() -> None:
    from device.sensors.humidity import _DEFAULT_MAX_STEP as humidity_step
    from device.sensors.temperature import _DEFAULT_MAX_STEP as temperature_step

    assert humidity_step < temperature_step
