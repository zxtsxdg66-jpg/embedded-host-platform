"""Launcher for the PC-side gateway (REST + WebSocket) that Android talks to.

Peer of scripts/run_gui.py: same composition-root role, same two modes,
but it serves an HTTP/WebSocket API instead of opening a PyQt6 window. It
does not start the GUI and the GUI does not start it -- for phase 1 they
are two independent processes, each building its own ApplicationRuntime.

Simulator mode (default) -- no hardware, no STM32 required::

    python scripts/run_api_server.py
    python scripts/run_api_server.py --host 0.0.0.0 --port 8000

    Registers the same three environmental sensor simulators the project
    already uses (temperature/humidity/noise) and drives them with
    SimulatorRuntimeRunner on a background thread, so a client sees data
    arriving continuously. **This data is software-simulated, not from a
    real STM32.**

Hardware mode -- real STM32 over a serial port::

    python scripts/run_api_server.py --mode hardware --port-serial COM3

    Same SerialChannel -> HardwareDeviceReceiver -> HardwareRuntimeRunner
    wiring scripts/run_gui.py already uses.

Note the two different "port" options: ``--port`` is the TCP port this HTTP
server listens on; ``--port-serial`` is the STM32's serial port. They are
named distinctly on purpose so they cannot be confused.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# Also put scripts/ itself on the path, for the same reason scripts/run_all.py
# does: importing this file as ``scripts.run_api_server`` (which is how the test suite
# reaches it) does not put its own directory on sys.path, and then the sibling
# ``automation_wiring`` import below fails with ModuleNotFoundError. It only
# worked by accident before -- scripts/run_all.py inserts the directory, and
# test collection happened to reach it first.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import uvicorn  # noqa: E402
from automation_wiring import (  # noqa: E402
    ACCEPTED_COMMANDS,
    LoggingApi,
    attach_export_status,
    attach_history,
    attach_language_model,
    enable_automations,
    logging_answer_sink,
    logging_question_observer,
    make_poll_once,
)  # noqa: E402
from question_log import QuestionLog  # noqa: E402  (same scripts/ directory)

from application.hardware_runner import HardwareRuntimeRunner  # noqa: E402
from application.hardware_runtime import HardwareDeviceReceiver  # noqa: E402
from application.runtime import ApplicationRuntime  # noqa: E402
from application.simulator_runner import SimulatorRuntimeRunner  # noqa: E402
from communication.loopback import LoopbackChannel  # noqa: E402
from communication.serial import SerialChannel  # noqa: E402
from device.capability import (  # noqa: E402
    ChannelDescriptor,
    CommandDescriptor,
    DeviceCapability,
)
from device.remote import RemoteDevice  # noqa: E402
from device.sensors.channels import (  # noqa: E402
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from device.sensors.humidity import HumiditySensorSimulator  # noqa: E402
from device.sensors.noise import NoiseSensorSimulator  # noqa: E402
from device.sensors.temperature import TemperatureSensorSimulator  # noqa: E402
from device.state import ConnectionState, DeviceStatus  # noqa: E402
from gateway.server import (  # noqa: E402
    assistant_sink,
    create_app,
    set_question_observer,
)
from llm.ollama import DEFAULT_MODEL as DEFAULT_LLM_MODEL  # noqa: E402

DEFAULT_HTTP_HOST = "0.0.0.0"
DEFAULT_HTTP_PORT = 8000
DEFAULT_SERIAL_BAUDRATE = 115200
DEFAULT_HARDWARE_DEVICE_ID = "mcu-1"
SIMULATOR_DEVICE_ID = "sim-env-1"


def build_simulator_runtime() -> tuple[
    ApplicationRuntime, list[tuple[str, str]], SimulatorRuntimeRunner
]:
    """Compose a runtime with the three environmental sensor simulators.

    Uses the project's existing sensor presets (device/sensors/), not the
    generic ch1/ch2 demo device scripts/run_gui.py registers -- an Android
    client testing the temperature/humidity/noise display needs those
    three channel names specifically.
    """
    runtime = ApplicationRuntime()

    # Each preset is its own SimulatorDevice with one channel; register all
    # three under one runtime so a client sees three devices' worth of
    # channels. They keep their own device ids so statistics/alarms stay
    # per-(device, channel) exactly as the PyQt6 UI already expects.
    temperature = TemperatureSensorSimulator(device_id=f"{SIMULATOR_DEVICE_ID}-temp")
    humidity = HumiditySensorSimulator(device_id=f"{SIMULATOR_DEVICE_ID}-humi")
    noise = NoiseSensorSimulator(device_id=f"{SIMULATOR_DEVICE_ID}-noise")

    targets: list[tuple[str, str]] = []
    for device, channel_id in (
        (temperature, TEMPERATURE_CHANNEL),
        (humidity, HUMIDITY_CHANNEL),
        (noise, NOISE_CHANNEL),
    ):
        runtime.register_device(
            device, LoopbackChannel(), accepted_commands=ACCEPTED_COMMANDS
        )
        targets.append((device.device_id, channel_id))

    # Same reasoning as scripts/run_gui.py: Simulator mode has no fan or
    # speaker, but the automations must still be exercisable without a
    # board. Commands go to the temperature simulator (ventilation is
    # primarily temperature-driven).
    enable_automations(runtime, temperature.device_id)

    runner = SimulatorRuntimeRunner(runtime, targets, poll_interval_seconds=1.0)
    return runtime, targets, runner


def build_hardware_runtime(
    serial_port: str,
    baudrate: int = DEFAULT_SERIAL_BAUDRATE,
    device_id: str = DEFAULT_HARDWARE_DEVICE_ID,
) -> tuple[ApplicationRuntime, list[tuple[str, str]], HardwareRuntimeRunner]:
    """Compose a runtime backed by a real SerialChannel/RemoteDevice.

    Same wiring as scripts/run_gui.py's build_hardware_runtime(), including
    the explicit ``watch_alarms_for()`` call that is required because
    ``runtime.devices.register(...)`` is used directly (to read back the
    assigned wire id) instead of the ``register_device()`` facade.
    """
    runtime = ApplicationRuntime()
    channel = SerialChannel(port=serial_port, baudrate=baudrate)
    device = RemoteDevice(
        device_id=device_id,
        capability=DeviceCapability(
            commands=(CommandDescriptor(command_type="PING"),),
            channels=(
                ChannelDescriptor(channel_id=TEMPERATURE_CHANNEL),
                ChannelDescriptor(channel_id=HUMIDITY_CHANNEL),
                ChannelDescriptor(channel_id=NOISE_CHANNEL),
            ),
        ),
        # 串口在下面的 register() 里被打开；打开成功即认为链路已建立。
        # 不设这个状态的话，RemoteDevice 会一直停留在 DeviceStatus 的默认值
        # DISCONNECTED，界面上就会出现"顶部显示未连接、数据却在刷新"的矛盾
        # ——SimulatorDevice 内部本来就把自己标为 CONNECTED（见 simulator.py），
        # 两种模式此前对同一件事给出了不一致的呈现。
        status=DeviceStatus(connection_state=ConnectionState.CONNECTED),
    )
    registration = runtime.devices.register(
        device, channel, accepted_commands=ACCEPTED_COMMANDS
    )
    runtime.watch_alarms_for(device)
    enable_automations(runtime, device.device_id)

    receiver = HardwareDeviceReceiver(
        device_id=device.device_id,
        wire_id=registration.wire_id,
        channel=channel,
        data_service=runtime.data_service,
    )
    runner = HardwareRuntimeRunner(receiver)
    targets = [
        (device_id, TEMPERATURE_CHANNEL),
        (device_id, HUMIDITY_CHANNEL),
        (device_id, NOISE_CHANNEL),
    ]
    return runtime, targets, runner


def _start_runner_thread(
    runtime: ApplicationRuntime,
    runner: SimulatorRuntimeRunner | HardwareRuntimeRunner,
    on_assistant_answer: Callable[[str, str], None] | None = None,
) -> threading.Thread:
    """Drive ``runner.run_once()`` on a daemon thread.

    The runners deliberately do not loop internally (see their docstrings);
    scripts/run_gui.py drives them with a QTimer, and this server -- which
    has no Qt event loop -- drives them with a plain thread instead. Daemon
    so Ctrl+C on the server exits cleanly without a join.

    ``on_assistant_answer`` is where a late model answer goes. Without it the
    phone would still get an answer from POST /assistant/ask, but never the
    improved one the model produces seconds later -- the same drift that once
    left ventilation dead in this launcher.
    """
    poll_once = make_poll_once(runtime, runner, on_assistant_answer)

    def _loop() -> None:
        runner.start()
        while runner.running:
            poll_once()
            time.sleep(runner.poll_interval_seconds)

    thread = threading.Thread(target=_loop, name="runtime-driver", daemon=True)
    thread.start()
    return thread


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("simulator", "hardware"),
        default="simulator",
        help="simulator (default, no hardware) or hardware (real serial port)",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HTTP_HOST,
        help=(
            "HTTP bind address. Default 0.0.0.0 so a phone on the same LAN "
            "can reach it; use 127.0.0.1 to restrict to this PC only."
        ),
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_HTTP_PORT, help="HTTP/WebSocket TCP port"
    )
    parser.add_argument(
        "--port-serial",
        default=None,
        help="STM32 serial port for --mode hardware, e.g. COM3 (required there)",
    )
    parser.add_argument(
        "--baudrate", type=int, default=DEFAULT_SERIAL_BAUDRATE, help="serial baud rate"
    )
    parser.add_argument(
        "--device-id",
        default=DEFAULT_HARDWARE_DEVICE_ID,
        help=f"device id for --mode hardware (default: {DEFAULT_HARDWARE_DEVICE_ID})",
    )
    parser.add_argument(
        "--llm-model",
        default=DEFAULT_LLM_MODEL,
        help=(
            "Ollama model used to reword answers "
            f"(default: {DEFAULT_LLM_MODEL}). Numbers never come from it."
        ),
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="skip the language model entirely; answers stay templated",
    )
    args = parser.parse_args(argv)
    if args.mode == "hardware" and not args.port_serial:
        parser.error("--mode hardware requires --port-serial, e.g. --port-serial COM3")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    # Annotated explicitly: the two branches return different runner types
    # (they share no base class, only the same run_once()/start()/running/
    # poll_interval_seconds shape that _start_runner_thread relies on), so
    # without this the variable would be inferred from whichever branch
    # comes first and the other assignment would be a type error.
    runner: HardwareRuntimeRunner | SimulatorRuntimeRunner
    if args.mode == "hardware":
        assert args.port_serial is not None  # enforced by _parse_args
        runtime, targets, runner = build_hardware_runtime(
            serial_port=args.port_serial,
            baudrate=args.baudrate,
            device_id=args.device_id,
        )
        mode_label = "hardware"
    else:
        runtime, targets, runner = build_simulator_runtime()
        mode_label = "simulator"

    # 问答日志见 scripts/question_log.py。本启动器此前**没有设置提问观察者**，
    # 手机在这里问过的话无人看得见；接日志时一并补上，
    # 否则三个启动器里又只有两个记得下来。
    question_log = QuestionLog()
    # 历史记录：无界面启动器同样要记，否则手机单独跑时什么都留不下。
    history_store = attach_history(runtime)
    # 只读台账，让"还有几个时段没传"这类问题在手机上也答得出。
    # **不装上传按钮**：这个启动器没有界面，而手机端按 6.1 节的决定
    # 本来就不给上传按钮——它看不到子进程的输出，失败了无从判断。
    export_ledger = attach_export_status(runtime)
    app = create_app(
        LoggingApi(runtime, question_log), subscriptions=targets, mode_label=mode_label
    )
    set_question_observer(app, logging_question_observer(question_log, None))

    # Attached here for the same reason the GUI launchers attach it: the
    # assistant works without a model (rules + templates), and with one it
    # also understands questions the rules miss. The phone reaches it through
    # POST /assistant/ask; late answers ride the WebSocket via assistant_sink.
    llm_available, llm_detail = attach_language_model(
        runtime, model=args.llm_model, enabled=not args.no_llm
    )
    if not llm_available:
        print(f"[llm] 未接入本地模型，问答只用模板：{llm_detail}")

    _start_runner_thread(
        runtime, runner, logging_answer_sink(question_log, assistant_sink(app))
    )

    print(f"[gateway] mode={mode_label}")
    if mode_label == "simulator":
        print("[gateway] NOTE: data is software-simulated, NOT from a real STM32.")
    print(f"[gateway] listening on http://{args.host}:{args.port}")
    print(f"[gateway] websocket at   ws://{args.host}:{args.port}/ws")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    # uvicorn.run 返回即服务已停，落盘最后一问。
    question_log.flush()
    runtime.history_recorder.flush()
    history_store.close()
    export_ledger.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
