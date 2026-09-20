"""Convert alarm-phrase WAV files into the firmware's PCM table.

Regenerates ``firmware/stm32f407/Drivers/BSP/AUDIO_ALERT/alert_pcm.c`` from
three WAV files, so the spoken alarm phrases live in the MCU's internal
flash as ``const`` arrays -- no SD card, no external SPI flash, no file
system (see that firmware module's header for why).

Usage
-----
    python scripts/wav_to_c.py 温度.wav 湿度.wav 噪声.wav

The three files are positional and **order matters**: temperature,
humidity, noise -- matching ``audio_alert_id_t`` in the firmware and
``AlertKind`` in ``src/service/alarm_announcer.py``.

Add ``-o`` to write somewhere else, and ``--dry-run`` to see the size
report without touching anything.

Input handling: stereo is mixed down to mono and any sample rate is
resampled to 16 kHz, so a file exported straight from a TTS tool usually
works as-is. Only 8/16/32-bit PCM WAV is accepted -- not compressed
formats (mp3, WAV with ADPCM), which ``wave`` cannot read; convert those
to plain PCM WAV first.

Standard library only (``wave``, ``audioop`` where available) -- this
script deliberately adds no dependency to the project.
"""

from __future__ import annotations

import argparse
import array
import sys
import wave
from pathlib import Path

TARGET_SAMPLE_RATE = 16000
"""Must match AUDIO_ALERT_SAMPLE_RATE in the firmware's audio_alert.h."""

CLIP_NAMES = ("TEMPERATURE", "HUMIDITY", "NOISE")

_DEFAULT_OUTPUT = (
    Path("firmware") / "stm32f407" / "Drivers" / "BSP" / "AUDIO_ALERT" / "alert_pcm.c"
)

# STM32F407ZGT6 has 1 MB of flash and the rest of the firmware uses ~19 KB,
# so this is a comfort threshold rather than a hard limit -- it exists to
# make an accidentally huge clip obvious instead of surfacing as a link
# error much later.
_SIZE_WARN_BYTES = 600 * 1024


def _read_wav_mono_16k(path: Path) -> array.array[int]:
    """Read ``path`` as 16-bit mono samples at TARGET_SAMPLE_RATE."""
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        width = source.getsampwidth()
        rate = source.getframerate()
        frames = source.readframes(source.getnframes())

    samples = _to_int16(frames, width)
    if channels > 1:
        samples = _mix_to_mono(samples, channels)
    if rate != TARGET_SAMPLE_RATE:
        samples = _resample(samples, rate, TARGET_SAMPLE_RATE)
    return samples


def _to_int16(frames: bytes, width: int) -> array.array[int]:
    """Convert raw PCM frames of the given sample width to signed 16-bit."""
    if width == 2:
        samples = array.array("h")
        samples.frombytes(frames)
        if sys.byteorder == "big":
            samples.byteswap()  # WAV data is little-endian
        return samples
    if width == 1:
        # 8-bit WAV is unsigned, centred on 128.
        return array.array("h", ((byte - 128) << 8 for byte in frames))
    if width == 4:
        wide = array.array("i")
        wide.frombytes(frames)
        if sys.byteorder == "big":
            wide.byteswap()
        return array.array("h", (value >> 16 for value in wide))
    raise ValueError(
        f"{width * 8}-bit WAV is not supported; export as 16-bit PCM WAV instead"
    )


def _mix_to_mono(samples: array.array[int], channels: int) -> array.array[int]:
    """Average interleaved channels down to one."""
    mono = array.array("h")
    for start in range(0, len(samples) - channels + 1, channels):
        total = sum(samples[start : start + channels])
        mono.append(int(total / channels))
    return mono


def _resample(
    samples: array.array[int], source_rate: int, target_rate: int
) -> array.array[int]:
    """Linear-interpolation resample.

    Good enough for short speech clips played through a small speaker;
    this is not trying to be a high-quality resampler. Export the WAV at
    16 kHz directly if you want to skip this step entirely.
    """
    if not samples:
        return samples
    ratio = source_rate / target_rate
    output_length = int(len(samples) / ratio)
    resampled = array.array("h")
    for index in range(output_length):
        position = index * ratio
        left = int(position)
        right = min(left + 1, len(samples) - 1)
        weight = position - left
        value = samples[left] * (1.0 - weight) + samples[right] * weight
        resampled.append(int(value))
    return resampled


SILENCE_RELATIVE_THRESHOLD = 0.02
"""Amplitude below this fraction of the clip's peak counts as silence."""

SILENCE_ABSOLUTE_FLOOR = 64
"""...but never treat anything above this raw amplitude as silence, so a
very quiet recording is not trimmed to nothing."""

SILENCE_GUARD_SECONDS = 0.02
"""Kept on each side of the speech, so trimming never clips the first
consonant or the tail of the last vowel."""


def _trim_silence(samples: array.array[int]) -> array.array[int]:
    """Drop the leading and trailing silence a TTS engine pads clips with.

    Worth doing rather than shipping the padding: Windows SAPI adds about
    0.1 s in front and **0.6 s behind** every phrase, which for a 1.4 s
    alarm is 44% of the clip -- and every byte of it lands in the MCU's
    internal flash. Trimming roughly halves the audio's flash footprint,
    and it also shortens the noise-blanking window, because that window is
    the clip's length plus a fixed reverberation tail (see main.c's
    NOISE_BLANK_TAIL_TICKS). Holding the speaker open through 0.6 s of
    digital silence would extend the window for nothing.

    Returns the input unchanged if it is silent throughout -- a caller
    replacing a clip with a deliberately empty one still gets an empty
    one, rather than a confusing error.
    """
    if not samples:
        return samples

    peak = max(abs(value) for value in samples)
    if peak == 0:
        return samples
    threshold = max(SILENCE_ABSOLUTE_FLOOR, int(peak * SILENCE_RELATIVE_THRESHOLD))

    first = next((i for i, v in enumerate(samples) if abs(v) > threshold), None)
    if first is None:
        return samples
    last = next(
        i for i in range(len(samples) - 1, -1, -1) if abs(samples[i]) > threshold
    )

    guard = int(SILENCE_GUARD_SECONDS * TARGET_SAMPLE_RATE)
    start = max(0, first - guard)
    end = min(len(samples), last + 1 + guard)
    return samples[start:end]


def _render_clip(name: str, samples: array.array[int]) -> str:
    """Render one clip as a C array definition."""
    if not samples:
        return f"static const int16_t s_pcm_{name.lower()}[1] = {{0}};\n"

    lines = [f"static const int16_t s_pcm_{name.lower()}[{len(samples)}] = {{"]
    per_line = 12
    for start in range(0, len(samples), per_line):
        chunk = samples[start : start + per_line]
        lines.append("    " + ",".join(f"{value:6d}" for value in chunk) + ",")
    lines.append("};\n")
    return "\n".join(lines)


def _render_file(clips: list[tuple[str, array.array[int]]]) -> str:
    body = [
        "/**",
        " ****************************************************************"
        "************************************",
        " * @file        alert_pcm.c",
        " * @brief       告警语音 PCM 数据 —— 由 scripts/wav_to_c.py 自动生成。",
        " *              请勿手工编辑数据部分，重跑脚本会整体覆盖。",
        " *",
        f" * 格式：{TARGET_SAMPLE_RATE} Hz / 16 位有符号 / 单声道。",
        " * 重新生成：",
        " *     python scripts/wav_to_c.py 温度.wav 湿度.wav 噪声.wav",
        " ****************************************************************"
        "************************************",
        " */",
        "",
        '#include "./BSP/AUDIO_ALERT/alert_pcm.h"',
        "",
    ]
    for name, samples in clips:
        body.append(_render_clip(name, samples))

    body.append("const alert_clip_t g_alert_clips[] =")
    body.append("{")
    for name, samples in clips:
        count = len(samples)
        suffix = "" if count else "   /* 空音频 */"
        body.append(
            f"    {{ s_pcm_{name.lower()}, {count}u }},"
            f"   /* AUDIO_ALERT_{name} */{suffix}"
        )
    body.append("};")
    body.append("")
    return "\n".join(body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把三个告警语音 WAV 转成固件用的 PCM 数组",
    )
    parser.add_argument("temperature", type=Path, help="温度超限语音 WAV")
    parser.add_argument("humidity", type=Path, help="湿度超限语音 WAV")
    parser.add_argument("noise", type=Path, help="噪声超限语音 WAV")
    parser.add_argument(
        "-o", "--output", type=Path, default=_DEFAULT_OUTPUT, help="输出的 .c 文件路径"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只报告体积，不写文件"
    )
    parser.add_argument(
        "--no-trim",
        action="store_true",
        help="保留首尾静音（默认裁掉，见 _trim_silence 的说明）",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    sources = [args.temperature, args.humidity, args.noise]
    clips: list[tuple[str, array.array[int]]] = []
    total_bytes = 0

    for name, path in zip(CLIP_NAMES, sources, strict=True):
        if not path.exists():
            print(f"找不到文件：{path}", file=sys.stderr)
            return 2
        try:
            samples = _read_wav_mono_16k(path)
        except (wave.Error, ValueError) as exc:
            print(f"{path} 读取失败：{exc}", file=sys.stderr)
            return 2

        raw_seconds = len(samples) / TARGET_SAMPLE_RATE
        if not args.no_trim:
            samples = _trim_silence(samples)

        size = len(samples) * 2
        total_bytes += size
        seconds = len(samples) / TARGET_SAMPLE_RATE
        trimmed = (
            "" if args.no_trim else f"  (裁前 {raw_seconds:4.2f}s)"
        )
        print(
            f"{name:12s} {path.name:28s} {seconds:5.2f}s  "
            f"{size / 1024:7.1f} KB{trimmed}"
        )
        clips.append((name, samples))

    print(f"{'合计':12s} {'':28s} {'':5s}   {total_bytes / 1024:7.1f} KB")
    if total_bytes > _SIZE_WARN_BYTES:
        print(
            f"⚠ 合计 {total_bytes / 1024:.1f} KB，占内部 Flash(1MB) 比例偏高，"
            "建议缩短语音或降低采样率",
            file=sys.stderr,
        )

    if args.dry_run:
        print("(--dry-run：未写入文件)")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_render_file(clips), encoding="utf-8", newline="\n")
    print(f"已写入 {args.output}")
    print("接下来用 Keil 重新编译烧录即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
