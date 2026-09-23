"""Tests for the interactive collection launcher's presets.

The launcher itself needs a terminal and a serial port, but its preset table
is data and can be checked. The one failure mode worth pinning down is silent:
``_CUES`` is keyed by the preset *label*, so renaming a label would stop the
timed prompts from firing without any error -- and the operator would only
find out afterwards, from a step-response run whose stimulus never got cued.
"""

from __future__ import annotations

from scripts.collect_data_launcher import _CUES, _PRESETS
from scripts.collect_experiment_data import parse_cues


def _labels() -> set[str]:
    return {label for _, _, _, label, _ in _PRESETS if label}


def test_every_cue_table_key_matches_an_existing_preset_label() -> None:
    assert set(_CUES) <= _labels()


def test_cue_arguments_are_well_formed() -> None:
    """Each preset's cues must survive the parser the collector will use."""
    for label, argv in _CUES.items():
        values = [argv[i + 1] for i in range(0, len(argv), 2)]
        assert all(flag == "--cue" for flag in argv[0::2]), label
        assert parse_cues(values), label


def test_noise_step_response_cues_match_its_three_phase_protocol() -> None:
    """60 s baseline / 60 s stimulus / 60 s recovery -- the design that fixes
    the limitations 第9章 9.4.5 records for the earlier humidity run."""
    cues = parse_cues(
        [_CUES["噪声阶跃响应"][i] for i in range(1, len(_CUES["噪声阶跃响应"]), 2)]
    )
    moments = [moment for moment, _ in cues]

    assert 60.0 in moments, "缺少开始施加声源的提示"
    assert 120.0 in moments, "缺少停止声源、进入恢复段的提示"


def test_presets_carry_a_duration_or_are_the_custom_entry() -> None:
    for text, duration, sample, label, _ in _PRESETS:
        assert text
        if label:
            assert duration > 0 and sample > 0, label
        else:
            assert duration == 0, "只有自定义项允许时长为 0"


def test_noise_presets_sample_faster_than_the_temperature_ones() -> None:
    """Sound pressure level moves far faster than temperature or humidity;
    a 15 s sampling interval would smear the step response into nothing."""
    by_label = {label: sample for _, _, sample, label, _ in _PRESETS if label}

    assert by_label["噪声阶跃响应"] < by_label["温湿度阶跃响应"]
