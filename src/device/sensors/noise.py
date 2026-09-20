"""NoiseSensorSimulator: a SimulatorDevice preset for a 40-60dB sensor with spikes.

See device/sensors/temperature.py's module docstring for the rationale
shared by all three sensor presets in this package. Noise differs from
temperature/humidity in shape: instead of a smooth trend, readings sit in
a baseline range with occasional short-lived spikes (a door slam, a
passing vehicle, ...), modeled by NoiseWithSpikesGenerator.
"""

from __future__ import annotations

from random import Random

from core.models import DeviceId
from device.sensors.channels import NOISE_CHANNEL
from device.sensors.generators import NoiseWithSpikesGenerator
from device.simulator import SimulatedChannel, SimulatorDevice

NOISE_BASELINE_MIN = 40.0
NOISE_BASELINE_MAX = 60.0
NOISE_SPIKE_MIN = 75.0
NOISE_SPIKE_MAX = 95.0
_DEFAULT_SPIKE_PROBABILITY = 0.15


class NoiseSensorSimulator(SimulatorDevice):
    """A SimulatorDevice pre-configured as a 40-60dB noise sensor with spikes."""

    def __init__(
        self,
        device_id: DeviceId = "noise-sensor-1",
        spike_probability: float = _DEFAULT_SPIKE_PROBABILITY,
        rng: Random | None = None,
    ) -> None:
        channel = SimulatedChannel(
            channel_id=NOISE_CHANNEL,
            generator=NoiseWithSpikesGenerator(
                baseline_low=NOISE_BASELINE_MIN,
                baseline_high=NOISE_BASELINE_MAX,
                spike_low=NOISE_SPIKE_MIN,
                spike_high=NOISE_SPIKE_MAX,
                spike_probability=spike_probability,
                rng=rng if rng is not None else Random(),
            ),
            description="Ambient noise level in dB (40-60 baseline, brief peaks)",
        )
        super().__init__(
            device_id=device_id,
            channels=[channel],
            name="Noise Sensor Simulator",
        )
