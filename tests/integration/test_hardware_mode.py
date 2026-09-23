"""Integration tests for dual device-mode support in DeviceManager/ApplicationRuntime.

Verifies that Simulator mode (SimulatorDevice) and Hardware mode
(RemoteDevice) can be registered, queried, and controlled through the
exact same ApplicationRuntime/LocalApi/DeviceManager code -- with no
if/else branching on device type anywhere above device/ -- per
docs/architecture.md.

RemoteDevice is paired with a LoopbackChannel here (not a real
SerialChannel/MCU) since this suite tests the *device abstraction*
dual-mode support, not communication hardware -- SerialChannel itself is
covered separately in tests/communication/test_serial.py.
"""

from __future__ import annotations

import json

import pytest

from api.local_api import LocalApi
from application.manager import COMMAND_ACK_CODE
from application.runtime import ApplicationRuntime
from communication.loopback import LoopbackChannel
from core.exceptions import ValidationError
from device.capability import CommandDescriptor, DeviceCapability
from device.remote import RemoteDevice
from device.simulator import ConstantValueGenerator, SimulatedChannel, SimulatorDevice
from protocol.encoder import encode
from protocol.frame import Frame
from service.command_models import Command, CommandStatus


def _make_remote_device(device_id: str = "mcu-1") -> RemoteDevice:
    capability = DeviceCapability(commands=(CommandDescriptor(command_type="PING"),))
    return RemoteDevice(device_id=device_id, capability=capability)


def _seed_ack(channel: LoopbackChannel, wire_id: int, accepted: bool) -> None:
    """Deposit a COMMAND_ACK_CODE frame on ``channel`` as if a real device
    had already answered it.

    DeviceManager.deliver()'s Hardware-mode path (RemoteDevice, unlike
    SimulatorDevice) waits for a genuine device-sent ack instead of
    fabricating one locally -- see application/manager.py's
    _await_device_ack docstring for why. A RemoteDevice test therefore
    has to play the device's part itself. LoopbackChannel's FIFO queue
    lets this be seeded before submit_command() even sends the request
    through it: deliver()'s wait loop doesn't care about arrival order,
    only about finding a frame addressed to this wire id with
    COMMAND_ACK_CODE, so a pre-seeded ack is picked up on the very first
    poll -- exactly like scripts/virtual_stm32.py answering a real
    request over an actual serial port, just without the wire delay.
    """
    payload = json.dumps({"status": "success" if accepted else "failed"}).encode(
        "utf-8"
    )
    ack = Frame(device_id=wire_id, command_type=COMMAND_ACK_CODE, payload=payload)
    channel.send(encode(ack))


# -- registration: both modes share the exact same DeviceManager path -------


def test_remote_device_registers_like_a_simulator_device() -> None:
    runtime = ApplicationRuntime()
    runtime.register_device(
        _make_remote_device("mcu-1"), LoopbackChannel(), accepted_commands=("PING",)
    )

    assert runtime.list_devices() == ["mcu-1"]


def test_simulator_and_remote_devices_coexist_in_one_runtime() -> None:
    runtime = ApplicationRuntime()
    simulator = SimulatorDevice(
        device_id="sim-1",
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(1))
        ],
    )
    runtime.register_device(simulator, LoopbackChannel())
    runtime.register_device(_make_remote_device("mcu-1"), LoopbackChannel())

    assert set(runtime.list_devices()) == {"sim-1", "mcu-1"}


# -- device queries work identically for a RemoteDevice ----------------------


def test_get_device_status_works_for_remote_device() -> None:
    runtime = ApplicationRuntime()
    runtime.register_device(_make_remote_device("mcu-1"), LoopbackChannel())

    status = runtime.get_device_status("mcu-1")

    assert status.device_id == "mcu-1"
    assert status.is_connected is False  # RemoteDevice starts DISCONNECTED
    assert status.is_occupied is False


def test_api_list_and_status_work_for_remote_device() -> None:
    runtime = ApplicationRuntime()
    runtime.register_device(_make_remote_device("mcu-1"), LoopbackChannel())
    api = LocalApi(runtime)

    assert api.list_devices() == ["mcu-1"]
    status = api.get_device_status("mcu-1")
    assert status.device_id == "mcu-1"


# -- control path works identically for a RemoteDevice -----------------------


def test_control_pipeline_works_for_remote_device() -> None:
    runtime = ApplicationRuntime()
    channel = LoopbackChannel()
    registration = runtime.devices.register(
        _make_remote_device("mcu-1"), channel, accepted_commands=("PING",)
    )
    _seed_ack(channel, registration.wire_id, accepted=True)

    assert runtime.acquire("mcu-1", "client-1") is True
    result = runtime.submit_command(
        Command(device_id="mcu-1", command_type="PING", origin="client-1")
    )

    assert result.status is CommandStatus.SUCCESS


def test_control_pipeline_rejects_unaccepted_command_for_remote_device() -> None:
    runtime = ApplicationRuntime()
    channel = LoopbackChannel()
    registration = runtime.devices.register(
        _make_remote_device("mcu-1"), channel, accepted_commands=("PING",)
    )
    runtime.acquire("mcu-1", "client-1")
    _seed_ack(channel, registration.wire_id, accepted=False)

    result = runtime.submit_command(
        Command(device_id="mcu-1", command_type="UNKNOWN", origin="client-1")
    )

    assert result.status is CommandStatus.FAILED


def test_control_pipeline_times_out_for_remote_device_with_no_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unlike Simulator mode (which cannot fail to self-answer), a
    RemoteDevice with nothing on the other end of the wire must not hang
    or crash -- it should fail cleanly after DeviceManager's ack timeout,
    surfacing as api.exceptions.CommandDeliveryError (see local_api.py).

    Timeout shrunk via monkeypatch so this test doesn't spend the real
    (production) 2-second timeout budget.
    """
    from api.exceptions import CommandDeliveryError

    monkeypatch.setattr("application.manager._COMMAND_ACK_TIMEOUT_SECONDS", 0.05)
    runtime = ApplicationRuntime()
    channel = LoopbackChannel()
    runtime.devices.register(
        _make_remote_device("mcu-1"), channel, accepted_commands=("PING",)
    )
    runtime.acquire("mcu-1", "client-1")
    api = LocalApi(runtime)

    with pytest.raises(CommandDeliveryError):
        api.submit_command(
            Command(device_id="mcu-1", command_type="PING", origin="client-1")
        )


# -- report_data() is Simulator-only, by design ------------------------------


def test_report_data_raises_for_remote_device() -> None:
    runtime = ApplicationRuntime()
    runtime.register_device(_make_remote_device("mcu-1"), LoopbackChannel())

    with pytest.raises(ValidationError):
        runtime.report_data("mcu-1", "ch1")


def test_report_data_still_works_for_simulator_device_alongside_remote() -> None:
    """Registering a RemoteDevice must not break existing SimulatorDevice behavior."""
    runtime = ApplicationRuntime()
    simulator = SimulatorDevice(
        device_id="sim-1",
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(42))
        ],
    )
    runtime.register_device(simulator, LoopbackChannel())
    runtime.register_device(_make_remote_device("mcu-1"), LoopbackChannel())

    point = runtime.report_data("sim-1", "ch1")

    assert point.value == 42
