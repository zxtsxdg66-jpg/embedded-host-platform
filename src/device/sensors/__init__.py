"""device.sensors: environmental sensor SimulatorDevice presets.

Corresponds to the "传感器应用模拟验证阶段" task -- validates the data
processing pipeline against a concrete, realistic multi-channel scenario
(temperature/humidity/noise) ahead of real STM32 + sensor hardware being
available, without changing device.simulator.SimulatorDevice,
device.remote.RemoteDevice, or any layer above device/.

Each class here is a thin SimulatorDevice subclass that only pre-configures
one channel and a domain-specific ValueGenerator (see generators.py);
device_id/capability/status and data generation all come from the
unmodified SimulatorDevice they subclass.

Not exported from device/__init__.py: the top-level device package is
deliberately generic ("not bound to any specific sensor"); these concrete
presets live in their own subpackage so importing them is an explicit,
scenario-specific choice (``from device.sensors import
TemperatureSensorSimulator``), not part of the generic device vocabulary.
"""

from device.sensors.generators import (
    NoiseWithSpikesGenerator,
    SmoothRandomWalkGenerator,
)
from device.sensors.humidity import HumiditySensorSimulator
from device.sensors.noise import NoiseSensorSimulator
from device.sensors.temperature import TemperatureSensorSimulator

__all__ = [
    "TemperatureSensorSimulator",
    "HumiditySensorSimulator",
    "NoiseSensorSimulator",
    "SmoothRandomWalkGenerator",
    "NoiseWithSpikesGenerator",
]
