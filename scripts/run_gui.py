"""Launcher for the PyQt6 upper-computer UI -- Simulator and Hardware modes.

Composes existing, unmodified src/ modules into a running GUI. This script
contains no business logic of its own and performs no MVC rewiring -- it
only constructs objects and calls their existing public APIs, exactly the
same composition pattern already used in tests/integration/ and
tests/ui/.

Two modes, selected with ``--mode``. Both are driven the same way: a
QTimer repeatedly calls ``runner.run_once()``.

Simulator mode (default, no hardware needed)::

    TemperatureSensorSimulator / HumiditySensorSimulator /
    NoiseSensorSimulator -> SimulatorRuntimeRunner
        -> ApplicationRuntime -> UI

Hardware mode (``--mode hardware --port COM3``)::

    SerialChannel -> HardwareDeviceReceiver -> HardwareRuntimeRunner
        -> ApplicationRuntime -> UI

Both report the same three channels (temperature/humidity/noise), so the
window looks identical either way -- Simulator mode is a usable stand-in
when no board is connected, not just a smoke test.

See docs/05_Test/Runtime_Mode.md for full usage instructions (including
COM port configuration) and docs/05_Test/Hardware_Simulation_Mode.md for
the architectural rationale behind the two modes.

UI boundary: src/ui/* is never told which mode is active and never
imports SerialChannel/HardwareDeviceReceiver/HardwareRuntimeRunner --
MainController only ever talks to api.ApiInterface, exactly as in
Simulator mode. All of the mode-specific wiring here (SerialChannel,
RemoteDevice, HardwareDeviceReceiver, HardwareRuntimeRunner, QTimer) lives
in this script, never in src/ui/.

Usage
-----
    python scripts/run_gui.py
    python scripts/run_gui.py --mode simulator
    python scripts/run_gui.py --mode hardware --port COM3
    python scripts/run_gui.py --mode hardware --port COM3 --baudrate 115200

or, on Windows, double-click ``run_gui_模拟数据界面.bat`` in the project root (forwards
any extra arguments, e.g. ``run_gui_模拟数据界面.bat --mode hardware --port COM3``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running this script directly (`python scripts/run_gui.py`) without
# first requiring `pip install -e .`: add src/ to sys.path before importing
# any project code. A no-op if the project is already installed.
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# Also put scripts/ itself on the path, for the same reason scripts/run_all.py
# does: importing this file as ``scripts.run_gui`` (which is how the test suite
# reaches it) does not put its own directory on sys.path, and then the sibling
# ``automation_wiring`` import below fails with ModuleNotFoundError. It only
# worked by accident before -- scripts/run_all.py inserts the directory, and
# test collection happened to reach it first.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from automation_wiring import (  # noqa: E402
    ACCEPTED_COMMANDS,
    LoggingApi,
    attach_export_status,
    attach_history,
    attach_language_model,
    enable_automations,
    logging_answer_sink,
    make_cloud_sync_runner,
    make_cloud_view_runner,
    make_poll_once,
)
from PyQt6.QtCore import QTimer  # noqa: E402 (see sys.path setup above)
from PyQt6.QtWidgets import QApplication  # noqa: E402
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
from llm.ollama import DEFAULT_MODEL as DEFAULT_LLM_MODEL  # noqa: E402
from ui.controller import MainController  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.theme import apply_theme  # noqa: E402

DEV_CLIENT_ID = "dev-gui"
DEFAULT_HARDWARE_DEVICE_ID = "mcu-1"
DEFAULT_BAUDRATE = 115200

# Simulator-mode device ids. One device per sensor, mirroring
# scripts/run_api_server.py, so statistics and alarms stay keyed per
# (device, channel) exactly as the UI already expects.
SIMULATOR_DEVICE_ID = "sim-env-1-temp"
SIMULATOR_DEVICE_ID_HUMIDITY = "sim-env-1-humi"
SIMULATOR_DEVICE_ID_NOISE = "sim-env-1-noise"

# Commands every registered device accepts, and the automation wiring that
# goes with them, now live in scripts/automation_wiring.py so all three
# launchers stay in step -- see that module's docstring for the bug that
# made it necessary.
_ACCEPTED_COMMANDS = ACCEPTED_COMMANDS


def build_simulator_runtime() -> tuple[ApplicationRuntime, SimulatorRuntimeRunner]:
    """Compose one ApplicationRuntime with the three environmental sensor
    simulators registered, plus the runner that makes them produce data.

    Returns a (runtime, runner) tuple, symmetric with
    :func:`build_hardware_runtime` -- in both modes the caller is
    responsible for driving ``runner.run_once()`` on a timer, because
    neither runner loops internally (see their docstrings).

    Two deliberate choices here:

    1. **A runner is returned at all.** Until 2026-08-15 this function
       returned only a runtime, and nothing in the running application
       ever called ``report_data()`` -- so Simulator mode opened a window
       that never displayed a single data point (verified empirically;
       ``report_data()`` was called only from tests). The QTimer added in
       :func:`main` is what fixes that.

    2. **temperature/humidity/noise rather than the previous generic
       ch1/ch2 demo device.** The window's metric cards, threshold
       alarms, and unit labels are all keyed to those three channel ids
       (see ui/main_window.py's ``_METRIC_CHANNELS`` and
       ui/channel_display.py). With ch1/ch2 the cards stayed blank and no
       alarm could ever fire, so Simulator mode could not serve as a
       no-hardware stand-in for the real thing. Using the same three
       channels Hardware mode reports makes the two modes visually
       identical, which is the whole point of having a Simulator fallback.
       It also matches what scripts/run_api_server.py already registers.
    """
    runtime = ApplicationRuntime()

    temperature = TemperatureSensorSimulator(device_id=SIMULATOR_DEVICE_ID)
    humidity = HumiditySensorSimulator(device_id=SIMULATOR_DEVICE_ID_HUMIDITY)
    noise = NoiseSensorSimulator(device_id=SIMULATOR_DEVICE_ID_NOISE)

    targets: list[tuple[str, str]] = []
    for device, channel_id in (
        (temperature, TEMPERATURE_CHANNEL),
        (humidity, HUMIDITY_CHANNEL),
        (noise, NOISE_CHANNEL),
    ):
        runtime.register_device(
            device, LoopbackChannel(), accepted_commands=_ACCEPTED_COMMANDS
        )
        targets.append((device.device_id, channel_id))

    # Simulator mode has no fan, but the ventilation path must still be
    # exercisable without hardware -- otherwise the feature could only ever
    # be demonstrated with the board attached. Commands go to the
    # temperature simulator (ventilation is primarily temperature-driven)
    # and are acknowledged locally by DeviceManager's simulated-ack path,
    # so everything above DataService behaves exactly as in Hardware mode.
    enable_automations(runtime, SIMULATOR_DEVICE_ID)

    runner = SimulatorRuntimeRunner(runtime, targets)
    return runtime, runner


def build_hardware_runtime(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    device_id: str = DEFAULT_HARDWARE_DEVICE_ID,
) -> tuple[ApplicationRuntime, HardwareRuntimeRunner]:
    """Compose one ApplicationRuntime backed by a real SerialChannel/RemoteDevice.

    Wires: SerialChannel -> HardwareDeviceReceiver -> HardwareRuntimeRunner,
    publishing into the *same* ApplicationRuntime.data_service that
    LocalApi/MainController already read from -- so from UI's point of
    view this is indistinguishable from Simulator mode.

    ``runtime.devices.register(...)`` (DeviceManager's own method, not the
    ApplicationRuntime facade) is called directly so the assigned wire id
    can be read back from the returned DeviceRegistration -- that wire id
    is what HardwareDeviceReceiver needs to know which frames are
    addressed to this device. Because of that, ``runtime.watch_alarms_for
    (device)`` must be called explicitly right after -- ``register_device()``
    (the facade method, unused here) is what normally does this
    automatically; see its and ``watch_alarms_for``'s docstrings in
    application/runtime.py.
    """
    runtime = ApplicationRuntime()
    channel = SerialChannel(port=port, baudrate=baudrate)
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
        device, channel, accepted_commands=_ACCEPTED_COMMANDS
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
    return runtime, runner


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("simulator", "hardware"),
        default="simulator",
        help="simulator (default, no hardware needed) or hardware (real SerialChannel)",
    )
    parser.add_argument(
        "--port",
        default=None,
        help="serial port for --mode hardware, e.g. COM3 (required in that mode)",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=DEFAULT_BAUDRATE,
        help=f"serial baud rate for --mode hardware (default: {DEFAULT_BAUDRATE})",
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
    if args.mode == "hardware" and not args.port:
        parser.error("--mode hardware requires --port, e.g. --port COM3")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    # Reuse an existing QApplication if one is already running (e.g. when
    # this module is imported from a test under pytest-qt) instead of
    # unconditionally constructing a second one, which PyQt6 forbids.
    app = QApplication.instance() or QApplication(sys.argv)
    assert isinstance(app, QApplication)
    apply_theme(app)

    # Both modes are driven identically: a QTimer repeatedly calls
    # runner.run_once(). Neither runner loops internally by design (see
    # application/hardware_runner.py and application/simulator_runner.py),
    # so the driver belongs here, in the composition root.
    timer: QTimer | None = None
    runner: HardwareRuntimeRunner | SimulatorRuntimeRunner
    if args.mode == "hardware":
        assert args.port is not None  # enforced by _parse_args
        runtime, runner = build_hardware_runtime(
            port=args.port, baudrate=args.baudrate, device_id=args.device_id
        )
    else:
        runtime, runner = build_simulator_runtime()

    mode_label = "硬件模式" if args.mode == "hardware" else "模拟模式"
    # 问答日志：真人问过的话是题库造不出来的语料，项目里真正有价值的缺陷全部
    # 来自真人试用（见 scripts/question_log.py 的模块文档）。只写本地文件，
    # 不上板载屏、不推手机。
    question_log = QuestionLog()
    # 历史记录：读数攒批写进 data/history.sqlite，退出前 close。
    # 设计见 docs/02_Architecture/History_And_Cloud_Design.md。
    history_store = attach_history(runtime)
    # 上云：助手只读台账、答出"还有几个时段没传"；真正上传由界面按钮触发。
    # 设计见 History_And_Cloud_Design.md 6.1 节——不进指令白名单，
    # 模型出标签、界面出按钮、人点击才执行。
    export_ledger = attach_export_status(runtime)
    api = LoggingApi(runtime, question_log)
    controller = MainController(api, client_id=DEV_CLIENT_ID)

    # Attach the local language model if one is reachable. Optional by
    # design: without it the assistant answers from rules and templates,
    # which is the default and always correct (see
    # docs/02_Architecture/Assistant_Design.md). Probed once here rather
    # than retried, so a missing model costs one failed connect at
    # start-up instead of one per question.
    llm_available, llm_detail = attach_language_model(
        runtime, model=args.llm_model, enabled=not args.no_llm
    )
    if not llm_available:
        print(f"[llm] 未接入本地模型，问答只用模板：{llm_detail}")

    # Drives run_once(), the automation dispatchers, and the assistant's
    # model polling. Neither runner loops internally by design (see
    # application/hardware_runner.py and application/simulator_runner.py),
    # so the driver belongs here, in the composition root.
    poll_once = make_poll_once(
        runtime,
        runner,
        on_assistant_answer=logging_answer_sink(
            question_log, controller.deliver_assistant_answer
        ),
    )

    timer = QTimer()
    timer.setInterval(int(runner.poll_interval_seconds * 1000))
    timer.timeout.connect(poll_once)
    runner.start()
    timer.start()

    window = MainWindow(controller, mode_label=mode_label)
    # Say it on screen, not only in this console: without a model every
    # answer stays labelled 「系统」, which looks exactly like a model that
    # is silently failing.
    window.set_assistant_model_status(llm_available, llm_detail)
    # 按钮背后的那个可调用对象在组合根构造：它要拉子进程，而 ui/ 不能
    # 创建、也不该知道有子进程这回事。点击留一行活动日志，与报警、
    # 移动端下发记在同一处。
    window.set_cloud_sync_runner(
        make_cloud_sync_runner(window.append_activity)
    )
    window.set_cloud_view_runner(
        make_cloud_view_runner(window.append_activity)
    )
    window.resize(1280, 820)
    window.show()

    # `timer`/`runner`/`runtime` stay referenced by this function's local
    # scope for as long as app.exec() blocks (i.e. for the whole GUI
    # session), so nothing here needs an extra keep-alive mechanism.
    exit_code = app.exec()
    # 最后一问可能还挂着等模型改写，退出前落盘，否则它就丢了。
    question_log.flush()
    # 最后一批读数可能还没满 50 条，退出前落盘再关库。
    runtime.history_recorder.flush()
    history_store.close()
    export_ledger.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
