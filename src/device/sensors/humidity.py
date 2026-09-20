"""HumiditySensorSimulator: a SimulatorDevice preset for a 40-80% sensor.

See device/sensors/temperature.py's module docstring for the rationale
shared by all three sensor presets in this package. Humidity uses a
smaller default max_step than temperature to reflect its slower-changing
nature ("变化缓慢").
"""

from __future__ import annotations

from random import Random

from core.models import DeviceId
from device.sensors.channels import HUMIDITY_CHANNEL
from device.sensors.generators import SmoothRandomWalkGenerator
from device.simulator import SimulatedChannel, SimulatorDevice

HUMIDITY_MIN = 40.0
HUMIDITY_MAX = 80.0
_DEFAULT_MAX_STEP = 0.15


class HumiditySensorSimulator(SimulatorDevice):
    """A SimulatorDevice pre-configured as a slowly-varying 40-80% humidity sensor."""

    def __init__(
        self,
        device_id: DeviceId = "humidity-sensor-1",
        max_step: float = _DEFAULT_MAX_STEP,
        rng: Random | None = None,
    ) -> None:
        channel = SimulatedChannel(
            channel_id=HUMIDITY_CHANNEL,
            generator=SmoothRandomWalkGenerator(
                low=HUMIDITY_MIN,
                high=HUMIDITY_MAX,
                max_step=max_step,
                rng=rng if rng is not None else Random(),
            ),
            description="Relative humidity percentage (40-80%)",
        )
        super().__init__(
            device_id=device_id,
            channels=[channel],
            name="Humidity Sensor Simulator",
        )
