"""TemperatureSensorSimulator: a SimulatorDevice preset for a 20-40C sensor.

Corresponds to the "传感器应用模拟验证阶段" task: validates the data
processing pipeline (SensorSimulator -> DataService -> SensorDataProcessor)
using a smoothly-varying, physically-plausible temperature reading, ahead
of a real STM32 + temperature sensor being available -- see
docs/architecture.md.

Composition only: this does not modify device.simulator.SimulatorDevice --
it subclasses it purely to pre-configure one channel and a domain-specific
ValueGenerator, keeping the sensor-specific preset a data-driven
configuration rather than an architecture change.
"""

from __future__ import annotations

from random import Random

from core.models import DeviceId
from device.sensors.channels import TEMPERATURE_CHANNEL
from device.sensors.generators import SmoothRandomWalkGenerator
from device.simulator import SimulatedChannel, SimulatorDevice

TEMPERATURE_MIN = 20.0
TEMPERATURE_MAX = 40.0
_DEFAULT_MAX_STEP = 0.3


class TemperatureSensorSimulator(SimulatorDevice):
    """A SimulatorDevice pre-configured as a smooth 20-40C temperature sensor."""

    def __init__(
        self,
        device_id: DeviceId = "temperature-sensor-1",
        max_step: float = _DEFAULT_MAX_STEP,
        rng: Random | None = None,
    ) -> None:
        channel = SimulatedChannel(
            channel_id=TEMPERATURE_CHANNEL,
            generator=SmoothRandomWalkGenerator(
                low=TEMPERATURE_MIN,
                high=TEMPERATURE_MAX,
                max_step=max_step,
                rng=rng if rng is not None else Random(),
            ),
            description="Ambient temperature in degrees Celsius (20-40C)",
        )
        super().__init__(
            device_id=device_id,
            channels=[channel],
            name="Temperature Sensor Simulator",
        )
