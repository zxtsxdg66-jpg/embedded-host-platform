"""The reserved command codes are a contract between two programs.

``application.manager.RESERVED_COMMAND_CODES`` and the
``PROTOCOL_CMD_*`` macros in the firmware header are compiled separately,
by different toolchains, and nothing at build time relates them. Until
this file existed the module docstring said so plainly -- "nothing but
review catches a mismatch" -- and a mismatch is not a crash: the board
acknowledges any command it does not recognise, so the failure looks like
a feature quietly not working.

Reading the header with a regex rather than parsing C is deliberate. The
macros are one line each by convention, and a test that needed a C parser
to guard six integers would not have been written at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from application.manager import RESERVED_COMMAND_CODES

HEADER = (
    Path(__file__).resolve().parents[2]
    / "firmware"
    / "stm32f407"
    / "Drivers"
    / "BSP"
    / "PROTOCOL"
    / "protocol_frame.h"
)

_MACRO = re.compile(r"^#define\s+PROTOCOL_CMD_(\w+)\s+0x([0-9A-Fa-f]+)u", re.MULTILINE)


def _firmware_codes() -> dict[str, int]:
    text = HEADER.read_text(encoding="utf-8")
    return {name: int(value, 16) for name, value in _MACRO.findall(text)}


def test_the_firmware_header_is_where_it_is_expected() -> None:
    """A moved header would make every assertion below vacuous."""
    assert HEADER.is_file()


@pytest.mark.parametrize(
    ("command_type", "code"), sorted(RESERVED_COMMAND_CODES.items())
)
def test_each_reserved_code_matches_the_firmware(command_type: str, code: int) -> None:
    """Parametrised so a mismatch names the command, not just "a dict differs"."""
    firmware = _firmware_codes()

    assert command_type in firmware, (
        f"{command_type} is pinned on the PC side but has no "
        f"PROTOCOL_CMD_{command_type} in the firmware header"
    )
    assert firmware[command_type] == code


def test_no_two_commands_share_a_code() -> None:
    """A duplicate would send two meanings down one code, and the board
    would act on whichever branch its switch reached first."""
    codes = list(RESERVED_COMMAND_CODES.values())

    assert len(codes) == len(set(codes))


def test_reserved_codes_stay_inside_their_block() -> None:
    """Dynamic assignment starts at 0x20 (see manager.py). A pinned code
    at or above it could collide with one handed out at runtime."""
    assert all(0x10 <= code < 0x20 for code in RESERVED_COMMAND_CODES.values())
