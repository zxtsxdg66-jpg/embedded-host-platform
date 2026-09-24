"""Hardware mode with fault injection: how the launchers wire it up.

The injector itself is tested in tests/application/test_fault_injection.py.
These tests hold the composition to three things: without the flag nothing
changes; with it, the receiver reads through the injector while the device
manager reads through the untouched view of the same wire; and the whole
path -- a (fake) serial port, the real receiver, the reconciliation --
agrees on what was injected.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from application.fault_injection import DEFAULT_FAULTS, FaultInjectingChannel
from communication.serial import SerialChannel
from protocol.encoder import encode
from protocol.frame import Frame
from scripts import run_all, run_api_server

_PORT = "COM_TEST"


class _FakeSerialPort:
    """serial.Serial stand-in whose read side the test fills."""

    def __init__(self) -> None:
        self.is_open = True
        self.buffer = bytearray()

    def write(self, data: bytes) -> int:
        return len(data)

    @property
    def in_waiting(self) -> int:
        return len(self.buffer)

    def read(self, size: int) -> bytes:
        chunk = bytes(self.buffer[:size])
        del self.buffer[:size]
        return chunk

    def close(self) -> None:
        self.is_open = False


@pytest.fixture
def port():
    fake = _FakeSerialPort()
    with (
        patch(
            "communication.serial.list_ports.comports",
            return_value=[SimpleNamespace(device=_PORT)],
        ),
        patch("communication.serial.serial.Serial", return_value=fake),
    ):
        yield fake


def _frame(value: float) -> bytes:
    payload = json.dumps({"channel": "temperature", "value": value}).encode()
    return encode(Frame(device_id=1, command_type=0x01, payload=payload))


# -- argument checks ------------------------------------------------------------------


@pytest.mark.parametrize("module", [run_api_server, run_all])
def test_hardware_mode_accepts_the_fault_flags(module) -> None:
    args = module._parse_args(
        ["--mode", "hardware", "--port-serial", _PORT,
         "--inject-faults", "--fault-length", "--fault-seed", "5"]
    )
    assert args.inject_faults and args.fault_length and args.fault_seed == 5


@pytest.mark.parametrize("module", [run_api_server, run_all])
def test_fault_options_need_the_main_switch(module) -> None:
    with pytest.raises(SystemExit):
        module._parse_args(
            ["--mode", "hardware", "--port-serial", _PORT, "--fault-length"]
        )


@pytest.mark.parametrize("module", [run_api_server, run_all])
def test_there_is_nothing_to_inject_into_in_simulator_mode(module) -> None:
    with pytest.raises(SystemExit):
        module._parse_args(["--mode", "simulator", "--inject-faults"])


def test_length_faults_are_a_hardware_mode_option() -> None:
    with pytest.raises(SystemExit):
        run_api_server._parse_args(
            ["--mode", "virtual", "--inject-faults", "--fault-length"]
        )


# -- composition ------------------------------------------------------------------


def test_without_the_flag_both_readers_share_the_plain_serial_channel(port) -> None:
    runtime, targets, runner = run_api_server.build_hardware_runtime(_PORT)
    device_id = targets[0][0]
    manager_channel = runtime.devices.get(device_id).channel
    assert isinstance(manager_channel, SerialChannel)
    assert runner.receiver._channel is manager_channel


def test_with_faults_the_receiver_reads_through_the_injector(port) -> None:
    runtime, targets, runner, injector = (
        run_api_server.build_hardware_runtime_with_faults(
            _PORT, faults=DEFAULT_FAULTS, fault_seed=1
        )
    )
    device_id = targets[0][0]
    assert runner.receiver._channel is injector
    assert isinstance(injector, FaultInjectingChannel)
    # The device manager gets the untouched view of the same wire.
    manager_channel = runtime.devices.get(device_id).channel
    assert manager_channel is not injector
    assert manager_channel.is_connected


def test_readings_from_the_port_reconcile_through_the_whole_path(port) -> None:
    runtime, _targets, runner, injector = (
        run_api_server.build_hardware_runtime_with_faults(
            _PORT, faults=DEFAULT_FAULTS, fault_seed=20260924
        )
    )
    points = []
    for batch in range(40):
        port.buffer.extend(b"".join(_frame(20 + batch + i / 10) for i in range(3)))
        points.extend(runner.run_once())
    for _ in range(20):
        points.extend(runner.run_once())

    report = injector.report(runtime.get_link_statistics())
    assert injector.counts().delivered_frames == 120
    assert report.bad_accepted == 0
    assert report.consistent is True, report.lines
    assert len(points) == 120 - injector.counts().bitflip


def test_the_final_report_says_whether_everything_matched(port, capsys) -> None:
    runtime, _targets, runner, injector = (
        run_api_server.build_hardware_runtime_with_faults(
            _PORT, faults=DEFAULT_FAULTS, fault_seed=3
        )
    )
    port.buffer.extend(b"".join(_frame(21.0 + i / 10) for i in range(30)))
    for _ in range(30):
        runner.run_once()
    run_api_server.print_fault_report(injector, runtime)
    out = capsys.readouterr().out
    assert "逐项一致" in out
    assert "被当作读数接受的错帧：0" in out
