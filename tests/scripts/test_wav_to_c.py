"""Tests for scripts/wav_to_c.py, the alarm-audio to PCM-table converter.

Focused on the silence trimming, because that is the part with a real
consequence: Windows SAPI pads every phrase with roughly 0.1 s in front
and 0.6 s behind, which for a 1.4 s alarm is 44% of the clip -- and every
byte lands in the MCU's internal flash. Trimming halved the audio's
footprint (135 KB -> 68 KB) and shortened the noise-blanking window with
it.
"""

from __future__ import annotations

import array
import math
import wave
from pathlib import Path

from scripts.wav_to_c import (
    SILENCE_GUARD_SECONDS,
    TARGET_SAMPLE_RATE,
    _trim_silence,
    main,
)


def _tone(seconds: float, amplitude: int = 12000) -> array.array[int]:
    count = int(seconds * TARGET_SAMPLE_RATE)
    return array.array(
        "h",
        (
            int(amplitude * math.sin(2 * math.pi * 440 * i / TARGET_SAMPLE_RATE))
            for i in range(count)
        ),
    )


def _silence(seconds: float) -> array.array[int]:
    return array.array("h", [0] * int(seconds * TARGET_SAMPLE_RATE))


def _write_wav(path: Path, samples: array.array[int]) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(TARGET_SAMPLE_RATE)
        handle.writeframes(samples.tobytes())


# -- silence trimming ---------------------------------------------------------


def test_leading_and_trailing_silence_are_removed() -> None:
    padded = _silence(0.1) + _tone(0.5) + _silence(0.6)

    trimmed = _trim_silence(padded)

    guard = 2 * SILENCE_GUARD_SECONDS
    assert 0.5 <= len(trimmed) / TARGET_SAMPLE_RATE <= 0.5 + guard + 0.01


def test_a_guard_margin_is_kept_so_speech_is_not_clipped() -> None:
    """Trimming exactly at the threshold would cut the first consonant."""
    padded = _silence(0.2) + _tone(0.3) + _silence(0.2)

    trimmed = _trim_silence(padded)

    assert len(trimmed) > 0.3 * TARGET_SAMPLE_RATE


def test_audio_without_padding_is_left_essentially_alone() -> None:
    tone = _tone(0.4)
    assert len(_trim_silence(tone)) == len(tone)


def test_a_fully_silent_clip_is_returned_unchanged() -> None:
    """A deliberately empty clip must stay empty rather than raise --
    alert_pcm.c ships as a silent placeholder before real audio exists."""
    silence = _silence(0.3)
    assert len(_trim_silence(silence)) == len(silence)


def test_an_empty_clip_is_handled() -> None:
    assert len(_trim_silence(array.array("h"))) == 0


def test_a_quiet_recording_is_not_trimmed_to_nothing() -> None:
    """The threshold is relative to the clip's own peak, with an absolute
    floor, so a softly recorded phrase survives."""
    quiet = _silence(0.1) + _tone(0.4, amplitude=300) + _silence(0.1)

    trimmed = _trim_silence(quiet)

    assert len(trimmed) > 0.3 * TARGET_SAMPLE_RATE


# -- end to end ---------------------------------------------------------------


def _three_wavs(tmp_path: Path) -> list[str]:
    paths = []
    for name in ("t", "h", "n"):
        path = tmp_path / f"{name}.wav"
        _write_wav(path, _silence(0.1) + _tone(0.5) + _silence(0.6))
        paths.append(str(path))
    return paths


def test_generated_table_is_much_smaller_with_trimming(tmp_path: Path) -> None:
    sources = _three_wavs(tmp_path)
    trimmed_out = tmp_path / "trimmed.c"
    kept_out = tmp_path / "kept.c"

    assert main([*sources, "-o", str(trimmed_out)]) == 0
    assert main([*sources, "-o", str(kept_out), "--no-trim"]) == 0

    assert trimmed_out.stat().st_size < kept_out.stat().st_size * 0.7


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    sources = _three_wavs(tmp_path)
    out = tmp_path / "nope.c"

    assert main([*sources, "-o", str(out), "--dry-run"]) == 0
    assert not out.exists()


def test_missing_source_is_reported_not_raised(tmp_path: Path) -> None:
    sources = _three_wavs(tmp_path)
    sources[1] = str(tmp_path / "absent.wav")

    assert main([*sources, "-o", str(tmp_path / "out.c")]) == 2


def test_generated_file_declares_all_three_clips(tmp_path: Path) -> None:
    out = tmp_path / "alert_pcm.c"
    assert main([*_three_wavs(tmp_path), "-o", str(out)]) == 0

    text = out.read_text(encoding="utf-8")
    assert "g_alert_clips" in text
    for name in ("temperature", "humidity", "noise"):
        assert name in text
