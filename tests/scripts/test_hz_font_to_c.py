"""Tests for scripts/hz_font_to_c.py, the LCD Chinese-font subset generator.

The generator's whole value is that the subset is derived from the
firmware sources rather than hand-maintained, so these tests concentrate
on the derivation: what gets collected, what gets left out, and whether
the emitted C table is stable enough to diff.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.hz_font_to_c import (
    BYTES_PER_GLYPH,
    FONT_SIZE,
    build_source,
    collect_ui_characters,
    glyph_to_ascii_art,
)


def _write(directory: Path, name: str, text: str) -> None:
    (directory / name).write_text(text, encoding="utf-8")


# -- which characters end up in the subset ------------------------------------


def test_collects_characters_from_ui_txt_literals(tmp_path: Path) -> None:
    _write(tmp_path, "ui.c", 'draw(UI_TXT("温度"));\ndraw(UI_TXT("湿度"));\n')

    assert collect_ui_characters(tmp_path) == ["度", "温", "湿"]


def test_chinese_in_comments_is_excluded(tmp_path: Path) -> None:
    """The reason the marker macro exists at all: these sources are
    commented in Chinese, and sweeping comments in would inflate the
    subset from dozens of glyphs to hundreds."""
    _write(
        tmp_path,
        "ui.c",
        "/* 这是一段中文注释，绝不该进字库 */\n"
        '// 行注释里的汉字同理\ndraw(UI_TXT("风扇"));\n',
    )

    assert collect_ui_characters(tmp_path) == ["扇", "风"]


def test_ascii_is_excluded(tmp_path: Path) -> None:
    """Digits and units come from the vendor font already compiled into
    lcdfont.h; embedding them again would waste flash."""
    _write(tmp_path, "ui.c", 'draw(UI_TXT("%RH dB 噪声"));\n')

    assert collect_ui_characters(tmp_path) == ["噪", "声"]


def test_non_ascii_punctuation_is_included(tmp_path: Path) -> None:
    """The degree sign is not ASCII, so it needs a glyph like any hanzi."""
    _write(tmp_path, "ui.c", 'draw(UI_TXT("°C"));\n')

    assert collect_ui_characters(tmp_path) == ["°"]


def test_headers_are_scanned_too(tmp_path: Path) -> None:
    _write(tmp_path, "ui.h", '#define TITLE UI_TXT("监测")\n')

    assert collect_ui_characters(tmp_path) == ["测", "监"]


def test_other_file_types_are_ignored(tmp_path: Path) -> None:
    _write(tmp_path, "notes.md", 'UI_TXT("站台")\n')

    assert collect_ui_characters(tmp_path) == []


def test_duplicates_collapse_and_order_is_by_code_point(tmp_path: Path) -> None:
    """Sorted output keeps regenerated tables diffable, and is what lets
    the firmware binary-search the table."""
    _write(tmp_path, "a.c", 'UI_TXT("噪声噪声")\n')
    _write(tmp_path, "b.c", 'UI_TXT("声音")\n')

    collected = collect_ui_characters(tmp_path)

    assert collected == sorted(set(collected), key=ord)
    assert collected == ["噪", "声", "音"]


def test_missing_directory_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        collect_ui_characters(tmp_path / "nope")


# -- generated C source -------------------------------------------------------


def test_build_source_emits_one_entry_per_character() -> None:
    characters = ["温", "度"]
    bitmaps = [bytes(BYTES_PER_GLYPH), bytes(BYTES_PER_GLYPH)]

    source = build_source(characters, bitmaps, "simhei.ttf")

    assert "const hz_glyph_t g_hz_glyphs[] =" in source
    assert "const uint16_t g_hz_glyph_count = 2u;" in source
    assert "{ 0x6E29u, {" in source
    assert "{ 0x5EA6u, {" in source
    assert '#include "./BSP/UI_SCREEN/ui_screen.h"' in source


def test_build_source_is_deterministic() -> None:
    characters = ["风", "扇"]
    bitmaps = [bytes(range(BYTES_PER_GLYPH % 256)) * 0 + bytes(BYTES_PER_GLYPH)] * 2

    assert build_source(characters, bitmaps, "f.ttf") == build_source(
        characters, bitmaps, "f.ttf"
    )


# -- rasterisation ------------------------------------------------------------


def test_rendered_glyphs_are_not_blank() -> None:
    """A blank glyph means the font has no coverage for the character --
    the failure mode this catches is a font substitution that silently
    yields empty cells."""
    pytest.importorskip("PIL")
    from PIL import ImageFont

    from scripts.hz_font_to_c import find_default_font, render_glyph

    try:
        font_path = find_default_font()
    except FileNotFoundError:
        pytest.skip("no CJK font available on this machine")

    font = ImageFont.truetype(str(font_path), FONT_SIZE)
    ascent, descent = font.getmetrics()
    offset = (FONT_SIZE - (ascent + descent)) // 2

    for char in "温湿度噪声风扇报警":
        bitmap = render_glyph(font, char, offset)
        assert len(bitmap) == BYTES_PER_GLYPH
        assert any(bitmap), f"{char} rendered blank"


def test_narrow_marks_are_pushed_to_the_right_of_their_cell() -> None:
    """The degree sign carries a full-width advance in a CJK font with
    its ink at the left; left as-is it would sit a space away from the
    C that follows it."""
    pytest.importorskip("PIL")
    from PIL import ImageFont

    from scripts.hz_font_to_c import find_default_font, render_glyph

    try:
        font_path = find_default_font()
    except FileNotFoundError:
        pytest.skip("no CJK font available on this machine")

    font = ImageFont.truetype(str(font_path), FONT_SIZE)
    ascent, descent = font.getmetrics()
    offset = (FONT_SIZE - (ascent + descent)) // 2
    art = glyph_to_ascii_art(render_glyph(font, "°", offset))

    rightmost = max(line.rfind("#") for line in art.splitlines())
    assert rightmost >= FONT_SIZE - 4
