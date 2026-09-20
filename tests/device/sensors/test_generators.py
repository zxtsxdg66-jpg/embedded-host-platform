from random import Random

import pytest

from device.sensors.generators import (
    NoiseWithSpikesGenerator,
    SmoothRandomWalkGenerator,
)

# -- SmoothRandomWalkGenerator ------------------------------------------------


def test_smooth_walk_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError):
        SmoothRandomWalkGenerator(low=40.0, high=20.0, max_step=0.5)


def test_smooth_walk_rejects_non_positive_max_step() -> None:
    with pytest.raises(ValueError):
        SmoothRandomWalkGenerator(low=20.0, high=40.0, max_step=0.0)


def test_smooth_walk_stays_within_bounds() -> None:
    generator = SmoothRandomWalkGenerator(
        low=20.0, high=40.0, max_step=0.5, rng=Random(1)
    )
    values = [generator.next_value() for _ in range(500)]
    assert all(20.0 <= value <= 40.0 for value in values)


def test_smooth_walk_changes_smoothly() -> None:
    """Consecutive values must never differ by more than max_step."""
    max_step = 0.3
    generator = SmoothRandomWalkGenerator(
        low=20.0, high=40.0, max_step=max_step, rng=Random(2)
    )
    values = [generator.next_value() for _ in range(200)]
    deltas = [abs(b - a) for a, b in zip(values, values[1:], strict=False)]
    assert all(delta <= max_step + 1e-9 for delta in deltas)


def test_smooth_walk_is_deterministic_given_same_seed() -> None:
    first = SmoothRandomWalkGenerator(low=0.0, high=10.0, max_step=1.0, rng=Random(7))
    second = SmoothRandomWalkGenerator(low=0.0, high=10.0, max_step=1.0, rng=Random(7))
    assert [first.next_value() for _ in range(20)] == [
        second.next_value() for _ in range(20)
    ]


def test_smooth_walk_is_not_constant() -> None:
    """A real random walk should actually move, not get stuck at one value."""
    generator = SmoothRandomWalkGenerator(
        low=20.0, high=40.0, max_step=0.5, rng=Random(3)
    )
    values = [generator.next_value() for _ in range(50)]
    assert len(set(values)) > 1


# -- NoiseWithSpikesGenerator --------------------------------------------------


def test_noise_generator_rejects_invalid_baseline_bounds() -> None:
    with pytest.raises(ValueError):
        NoiseWithSpikesGenerator(
            baseline_low=60.0, baseline_high=40.0, spike_low=75.0, spike_high=95.0
        )


def test_noise_generator_rejects_invalid_spike_bounds() -> None:
    with pytest.raises(ValueError):
        NoiseWithSpikesGenerator(
            baseline_low=40.0, baseline_high=60.0, spike_low=95.0, spike_high=75.0
        )


def test_noise_generator_rejects_invalid_probability() -> None:
    with pytest.raises(ValueError):
        NoiseWithSpikesGenerator(
            baseline_low=40.0,
            baseline_high=60.0,
            spike_low=75.0,
            spike_high=95.0,
            spike_probability=1.5,
        )


def test_noise_generator_always_baseline_when_probability_zero() -> None:
    generator = NoiseWithSpikesGenerator(
        baseline_low=40.0,
        baseline_high=60.0,
        spike_low=75.0,
        spike_high=95.0,
        spike_probability=0.0,
        rng=Random(4),
    )
    values = [generator.next_value() for _ in range(100)]
    assert all(40.0 <= value <= 60.0 for value in values)


def test_noise_generator_always_spike_when_probability_one() -> None:
    generator = NoiseWithSpikesGenerator(
        baseline_low=40.0,
        baseline_high=60.0,
        spike_low=75.0,
        spike_high=95.0,
        spike_probability=1.0,
        rng=Random(5),
    )
    values = [generator.next_value() for _ in range(100)]
    assert all(75.0 <= value <= 95.0 for value in values)


def test_noise_generator_produces_both_baseline_and_spikes_over_many_samples() -> None:
    generator = NoiseWithSpikesGenerator(
        baseline_low=40.0,
        baseline_high=60.0,
        spike_low=75.0,
        spike_high=95.0,
        spike_probability=0.3,
        rng=Random(6),
    )
    values = [generator.next_value() for _ in range(300)]
    assert any(value <= 60.0 for value in values)
    assert any(value >= 75.0 for value in values)
