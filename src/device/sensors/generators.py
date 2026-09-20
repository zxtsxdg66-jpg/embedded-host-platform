"""Domain-specific ValueGenerator implementations for environmental sensors.

Corresponds to the "传感器应用模拟验证阶段" task: device.simulator.ValueGenerator
already supports constant/sequence/random-uniform generation, but none of
those produce a smoothly trending or occasionally-spiking series. These two
new generators extend that same abstraction (imported, not modified) with:

- SmoothRandomWalkGenerator: a bounded random walk, for readings that
  should drift continuously rather than jump between independent samples
  (temperature, humidity).
- NoiseWithSpikesGenerator: a baseline range with a configurable chance of
  a short-lived spike into a higher range (noise/sound level).

Neither subclass touches device/simulator.py -- both only import the public
ValueGenerator ABC from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

from device.simulator import ValueGenerator


@dataclass
class SmoothRandomWalkGenerator(ValueGenerator):
    """Bounded random-walk generator, for smoothly/slowly-changing readings.

    Each call nudges the current value by a small random step (uniformly
    distributed in ``[-max_step, max_step]``) and clamps the result back
    into ``[low, high]``, producing a continuous, physically-plausible
    trend rather than independent random samples on every call.
    """

    low: float
    high: float
    max_step: float
    rng: Random = field(default_factory=Random)
    _current: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.low >= self.high:
            raise ValueError("low must be less than high")
        if self.max_step <= 0:
            raise ValueError("max_step must be positive")
        self._current = self.rng.uniform(self.low, self.high)

    def next_value(self) -> float:
        step = self.rng.uniform(-self.max_step, self.max_step)
        self._current = min(self.high, max(self.low, self._current + step))
        return self._current


@dataclass
class NoiseWithSpikesGenerator(ValueGenerator):
    """Mostly-baseline generator with occasional short-lived spikes.

    Values are drawn from ``[baseline_low, baseline_high]`` most of the
    time; with probability ``spike_probability`` a value is drawn instead
    from ``[spike_low, spike_high]`` to simulate a brief loud event, e.g.
    for a noise/sound-level sensor.
    """

    baseline_low: float
    baseline_high: float
    spike_low: float
    spike_high: float
    spike_probability: float = 0.1
    rng: Random = field(default_factory=Random)

    def __post_init__(self) -> None:
        if self.baseline_low >= self.baseline_high:
            raise ValueError("baseline_low must be less than baseline_high")
        if self.spike_low >= self.spike_high:
            raise ValueError("spike_low must be less than spike_high")
        if not 0.0 <= self.spike_probability <= 1.0:
            raise ValueError("spike_probability must be within 0..1")

    def next_value(self) -> float:
        if self.rng.random() < self.spike_probability:
            return self.rng.uniform(self.spike_low, self.spike_high)
        return self.rng.uniform(self.baseline_low, self.baseline_high)
