"""Generate the firmware's embedded Chinese font subset from the UI sources.

The STM32 板载 LCD needs Chinese glyphs, but a full GBK font is 250 KB+ and
would have to live in an external SPI flash whose bus collides with the JTAG
pins -- disabling JTAG right before a thesis defence trades a debugging
lifeline for glyphs we do not need.  The screen only ever shows a few dozen
fixed words, so this script renders exactly those into a subset table that
fits in internal flash (roughly 3 KB at 24x24).

How the character set is decided
--------------------------------
The subset is **not** a hand-maintained list -- it is scanned out of the
firmware UI sources themselves.  Every on-screen string in
``Drivers/BSP/UI_SCREEN`` is wrapped in the marker macro ``UI_TXT("...")``
(defined as a no-op in ``ui_screen.h``), and this script collects the
characters from those literals only.  Chinese in *comments* is therefore
excluded, and a word added to the UI can never silently miss its glyph: the
next regeneration picks it up.

Usage
-----
    python scripts/hz_font_to_c.py                  # regenerate in place
    python scripts/hz_font_to_c.py --dry-run        # size report only
    python scripts/hz_font_to_c.py --font C:/Windows/Fonts/simhei.ttf

Requires Pillow (the only third-party dependency in the firmware toolchain
side of this project; the PC application itself does not use it).

Bitmap format: 24x24, row-major, 3 bytes per row, MSB = leftmost pixel --
matching ``hz_font_draw_char`` in ``ui_screen.c``.  Deliberately *not* the
column-major layout of the vendor ASCII font in ``lcdfont.h``: that layout
exists to suit ``lcd_show_char``'s point-by-point loop, while our glyph
blitter writes whole rows through ``lcd_set_cursor`` + ``LCD_RAM``, which is
markedly faster and wants rows.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

FONT_SIZE = 24
"""Cell size in pixels. Must match HZ_FONT_SIZE in ui_screen.h."""

BYTES_PER_ROW = (FONT_SIZE + 7) // 8
BYTES_PER_GLYPH = BYTES_PER_ROW * FONT_SIZE

INK_THRESHOLD = 128
"""Grayscale level at or above which a rendered pixel counts as ink."""

UI_TEXT_PATTERN = re.compile(r'UI_TXT\(\s*"((?:[^"\\]|\\.)*)"\s*\)')
"""Matches the marker macro that wraps every on-screen string literal."""

DEFAULT_FONT_CANDIDATES = (
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)

_BANNER = " " + "*" * 100
"""The 100-star rule every ALIENTEK-style file header uses. Built rather
than inlined so the generator itself stays inside the line-length limit."""

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = _PROJECT_ROOT / "firmware/stm32f407/Drivers/BSP/UI_SCREEN"
DEFAULT_OUTPUT = DEFAULT_SOURCE_DIR / "hzfont.c"


def find_default_font() -> Path:
    """Locate a usable CJK font, preferring SimHei.

    SimHei is preferred over Microsoft YaHei because its uniform stroke
    weight survives a 24x24 threshold better -- YaHei's thin hairlines drop
    out entirely at this size.

    :raises FileNotFoundError: if no candidate exists on this machine.
    """
    for candidate in DEFAULT_FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return path
    raise FileNotFoundError(
        "no CJK font found in the default locations; pass --font explicitly"
    )


def collect_ui_characters(source_dir: Path) -> list[str]:
    """Scan ``UI_TXT("...")`` literals and return the non-ASCII characters.

    ASCII is excluded on purpose: digits, units and punctuation are drawn
    from the vendor font already compiled into ``lcdfont.h``, so embedding
    them again would waste flash.

    :param source_dir: directory holding the UI sources (searched recursively).
    :return: sorted, de-duplicated characters, ordered by code point so the
        generated table is stable across runs and diffs stay readable.
    """
    if not source_dir.is_dir():
        raise FileNotFoundError(f"UI source directory not found: {source_dir}")

    characters: set[str] = set()
    for path in sorted(source_dir.rglob("*")):
        if path.suffix not in {".c", ".h"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for literal in UI_TEXT_PATTERN.findall(text):
            characters.update(char for char in literal if ord(char) >= 0x80)

    return sorted(characters, key=ord)


def render_glyph(font, char: str, baseline_offset: int) -> bytes:
    """Rasterise one character into a row-major 24x24 bitmap.

    :param font: a ``PIL.ImageFont`` instance already sized to FONT_SIZE.
    :param baseline_offset: vertical offset applied to every glyph, so the
        whole set shares one baseline instead of each being centred on its
        own ink -- otherwise punctuation such as the full-width colon would
        float to the middle of the line.
    """
    from PIL import Image, ImageDraw

    image = Image.new("L", (FONT_SIZE, FONT_SIZE), color=0)
    draw = ImageDraw.Draw(image)

    advance = draw.textlength(char, font=font)
    x = int(round((FONT_SIZE - advance) / 2))
    draw.text((x, baseline_offset), char, font=font, fill=255)

    # Nudge narrow marks to the right edge of their cell. Full-width CJK
    # fills the cell and is unaffected; the degree sign is the case that
    # matters -- in a CJK font it carries a *full-width advance* with its ink
    # tucked to the left, so leaving it where the font puts it opens a
    # space-wide gap between the ° and the C that follows it. The test is on
    # actual ink, not on the advance width, precisely because the advance
    # lies about how wide the mark really is.
    ink = image.getbbox()
    if ink is not None and (ink[2] - ink[0]) < FONT_SIZE * 0.6:
        shift = (FONT_SIZE - 2) - ink[2]
        if shift > 0:
            from PIL import ImageChops

            image = ImageChops.offset(image, shift, 0)

    pixels = image.load()
    out = bytearray(BYTES_PER_GLYPH)
    for y in range(FONT_SIZE):
        for x_pos in range(FONT_SIZE):
            if pixels[x_pos, y] >= INK_THRESHOLD:
                out[y * BYTES_PER_ROW + (x_pos >> 3)] |= 0x80 >> (x_pos & 7)
    return bytes(out)


def glyph_to_ascii_art(bitmap: bytes) -> str:
    """Render a glyph bitmap as text, for eyeballing the result in a terminal."""
    lines = []
    for y in range(FONT_SIZE):
        row = bitmap[y * BYTES_PER_ROW:(y + 1) * BYTES_PER_ROW]
        chars = []
        for x in range(FONT_SIZE):
            chars.append("#" if row[x >> 3] & (0x80 >> (x & 7)) else ".")
        lines.append("".join(chars))
    return "\n".join(lines)


def _describe(char: str) -> str:
    """Human-readable label for the per-glyph comment in the generated table."""
    try:
        name = unicodedata.name(char)
    except ValueError:  # pragma: no cover - unnamed code points are not expected
        name = "UNNAMED"
    return f"{char}  U+{ord(char):04X}  {name}"


def build_source(characters: list[str], bitmaps: list[bytes], font_name: str) -> str:
    """Render the generated ``hzfont.c`` text."""
    lines = [
        "/**",
        _BANNER,
        " * @file        hzfont.c",
        " * @brief       LCD 中文字库子集（自动生成，请勿手工编辑）",
        " *",
        " * 由 scripts/hz_font_to_c.py 从 Drivers/BSP/UI_SCREEN 下所有",
        " * UI_TXT(\"...\") 字符串字面量中出现的汉字自动提取并渲染而成。",
        f" * 字体 {font_name}，{FONT_SIZE}x{FONT_SIZE} 点阵，行优先存储，",
        " * 每行 3 字节，最高位对应最左像素。",
        " *",
        " * 要新增屏幕文案：直接改 ui_screen.c 里的 UI_TXT(\"...\") 文本，然后重新运行",
        " *     python scripts/hz_font_to_c.py",
        " * 不需要、也不应该手工往本文件里添加点阵——手工添加的内容会在下次生成时丢失。",
        " *",
        " * 为什么用子集而不是完整 GBK 字库：完整字库需外挂 SPI Flash，其总线会",
        " * 占用 JTAG 引脚，答辩前关掉调试口得不偿失。详细理由见本文件的生成脚本",
        " * scripts/hz_font_to_c.py 的模块注释。",
        _BANNER,
        " */",
        '#include "./BSP/UI_SCREEN/ui_screen.h"',
        "",
        f"/* 共 {len(characters)} 个汉字/全角符号，"
        f"合计 {len(characters) * (BYTES_PER_GLYPH + 4)} 字节（含索引开销） */",
        "const hz_glyph_t g_hz_glyphs[] =",
        "{",
    ]

    for char, bitmap in zip(characters, bitmaps, strict=True):
        lines.append(f"    /* {_describe(char)} */")
        lines.append(f"    {{ 0x{ord(char):04X}u, {{")
        for y in range(FONT_SIZE):
            row = bitmap[y * BYTES_PER_ROW:(y + 1) * BYTES_PER_ROW]
            body = ", ".join(f"0x{value:02X}u" for value in row)
            lines.append(f"        {body},")
        lines.append("    } },")

    lines.append("};")
    lines.append("")
    lines.append(f"const uint16_t g_hz_glyph_count = {len(characters)}u;")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--font",
        type=Path,
        default=None,
        help="TTF/TTC font file to rasterise from (default: SimHei if present)",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="directory scanned for UI_TXT(\"...\") literals",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="path of the generated C file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the character set and size without writing anything",
    )
    parser.add_argument(
        "--preview",
        metavar="CHARS",
        default="",
        help="print ASCII art for these characters, to check rendering quality",
    )
    args = parser.parse_args(argv)

    try:
        from PIL import ImageFont
    except ImportError:
        print(
            "Pillow is required: pip install Pillow",
            file=sys.stderr,
        )
        return 2

    try:
        font_path = args.font if args.font is not None else find_default_font()
        characters = collect_ui_characters(args.source_dir)
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if not characters:
        print(
            f"error: no UI_TXT(\"...\") literals with non-ASCII characters found "
            f"under {args.source_dir}",
            file=sys.stderr,
        )
        return 2

    font = ImageFont.truetype(str(font_path), FONT_SIZE)
    ascent, descent = font.getmetrics()
    # One shared baseline for the whole subset (see render_glyph).
    baseline_offset = (FONT_SIZE - (ascent + descent)) // 2

    bitmaps = [render_glyph(font, char, baseline_offset) for char in characters]

    blank = [
        char
        for char, bitmap in zip(characters, bitmaps, strict=True)
        if not any(bitmap)
    ]
    if blank:
        print(
            f"warning: {len(blank)} character(s) rendered blank -- the font may "
            f"not cover them: {''.join(blank)}",
            file=sys.stderr,
        )

    if args.preview:
        for char in args.preview:
            if char in characters:
                print(f"--- {_describe(char)} ---")
                print(glyph_to_ascii_art(bitmaps[characters.index(char)]))
            else:
                print(f"--- {char!r} is not in the subset ---")

    total_bytes = len(characters) * (BYTES_PER_GLYPH + 4)
    print(f"font      : {font_path}")
    print(f"characters: {len(characters)}  {''.join(characters)}")
    print(f"flash cost: {total_bytes} bytes ({total_bytes / 1024:.1f} KB)")

    if args.dry_run:
        print("dry run -- nothing written")
        return 0

    source = build_source(characters, bitmaps, font_path.name)
    args.output.write_text(source, encoding="utf-8", newline="\n")
    print(f"written   : {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
