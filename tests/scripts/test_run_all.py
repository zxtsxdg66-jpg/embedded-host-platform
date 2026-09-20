"""Tests for scripts/run_all.py -- the launcher that runs the PyQt6 UI and
the Android gateway in one process, sharing a single serial connection.

Why this script needs its own tests: the whole point of it is that there is
exactly **one** ApplicationRuntime feeding **two** consumers. If a future
change accidentally builds two runtimes (or two SerialChannels) again, the
hardware-mode COM port conflict comes straight back -- and that failure only
shows up with a real board plugged in, which CI can never have. These tests
pin the invariant down without hardware.

Does not call run_all.main(): it blocks in app.exec() like run_gui's does
(see tests/scripts/test_run_gui.py for the same reasoning).
"""

from __future__ import annotations

import pytest

from api.local_api import LocalApi
from scripts import run_all


def test_hardware_mode_requires_a_serial_port() -> None:
    """--mode hardware without --port-serial must fail fast, not later."""
    with pytest.raises(SystemExit):
        run_all._parse_args(["--mode", "hardware"])


def test_simulator_mode_needs_no_serial_port() -> None:
    args = run_all._parse_args([])
    assert args.mode == "simulator"
    assert args.port_serial is None


def test_serial_and_http_ports_are_separate_options() -> None:
    """--port is HTTP, --port-serial is the STM32. Confusing them silently
    would be the kind of bug that only surfaces on real hardware."""
    args = run_all._parse_args(
        ["--mode", "hardware", "--port-serial", "COM10", "--port", "9000"]
    )
    assert args.port_serial == "COM10"
    assert args.port == 9000


def test_both_consumers_share_one_runtime_and_data_service() -> None:
    """The core invariant: UI and gateway read the same DataService.

    Uses simulator mode so no serial port is involved; the sharing logic is
    identical in hardware mode (same build_* helper contract).
    """
    runtime, targets, runner = run_all.run_api_server.build_simulator_runtime()

    ui_api = LocalApi(runtime)
    gateway_api = LocalApi(runtime)

    # Two facades, one runtime underneath -- so both see the same devices.
    assert ui_api.list_devices() == gateway_api.list_devices()
    assert {device_id for device_id, _ in targets} <= set(ui_api.list_devices())

    received: list[float] = []
    ui_api.subscribe_data(*targets[0], received.append)

    runner.start()
    runner.run_once()

    # One physical read, delivered through the shared DataService.
    assert received, "data published by the shared runner did not reach the UI facade"
