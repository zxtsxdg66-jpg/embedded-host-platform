"""The ``--mode virtual`` composition of scripts/run_api_server.py, end to end.

A virtual STM32 on a thread writes real frames into a pipe; the ordinary
Hardware-mode receiver reads them; the gateway exposes what the link did.
Nothing below the channel is simulated away -- which is why this mode
exists (docs/decisions/08-web.md).
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from api.local_api import LocalApi
from gateway.server import create_app
from scripts.run_api_server import (
    WEB_DIR,
    build_simulator_runtime,
    build_virtual_runtime,
    mount_web_console,
)


def _drive_until(runner, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    runner.start()
    while time.monotonic() < deadline:
        runner.run_once()
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition not reached before timeout")


def test_virtual_mode_delivers_real_frames_through_the_hardware_receiver() -> None:
    runtime, targets, runner, stop = build_virtual_runtime()
    received: list[object] = []
    for device_id, channel in targets:
        runtime.subscribe(device_id, channel, received.append)
    try:
        _drive_until(runner, lambda: len(received) >= 3)
        stats = runtime.get_link_statistics()
        assert stats.active is True
        assert stats.bytes_received > 0
        assert stats.frames >= 3
        assert stats.checksum_errors == 0
    finally:
        stop.set()


def test_the_gateway_reports_link_statistics_in_virtual_mode() -> None:
    runtime, targets, runner, stop = build_virtual_runtime()
    try:
        _drive_until(runner, lambda: runtime.get_link_statistics().frames >= 3)
        app = create_app(LocalApi(runtime), subscriptions=targets, mode_label="virtual")
        with TestClient(app) as client:
            body = client.get("/link/statistics").json()
        assert body["active"] is True
        assert body["frames"] >= 3
    finally:
        stop.set()


def test_the_link_is_reported_inactive_in_simulator_mode() -> None:
    """No byte stream exists in Simulator mode; the console must say so
    rather than show a row of zeros that looks like a healthy link."""
    runtime, targets, _ = build_simulator_runtime()
    app = create_app(LocalApi(runtime), subscriptions=targets, mode_label="simulator")
    with TestClient(app) as client:
        assert client.get("/link/statistics").json()["active"] is False


def test_link_events_reach_websocket_clients() -> None:
    runtime, targets, runner, stop = build_virtual_runtime()
    try:
        app = create_app(LocalApi(runtime), subscriptions=targets, mode_label="virtual")
        with TestClient(app) as client, client.websocket_connect("/ws") as websocket:
            _drive_until(runner, lambda: runtime.get_link_statistics().frames >= 1)
            kinds = set()
            for _ in range(12):
                message = websocket.receive_json()
                kinds.add(message["type"])
                if message["type"] == "link_event":
                    assert message["raw"].startswith("AA 55")
                    break
            assert "link_event" in kinds
    finally:
        stop.set()


def test_the_web_console_is_served_only_when_the_directory_exists() -> None:
    runtime, targets, _ = build_simulator_runtime()
    app = create_app(LocalApi(runtime), subscriptions=targets)
    mounted = mount_web_console(app)
    assert mounted is (WEB_DIR / "index.html").is_file()
    if mounted:
        with TestClient(app) as client:
            assert client.get("/web/").status_code == 200
