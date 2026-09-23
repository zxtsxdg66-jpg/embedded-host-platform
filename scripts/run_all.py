"""Launcher that runs the PyQt6 desktop UI **and** the Android gateway together.

Why this script exists
----------------------
scripts/run_gui.py and scripts/run_api_server.py each build their own
``ApplicationRuntime`` and, in hardware mode, each open their own
``SerialChannel``. That is fine in Simulator mode (two processes, two
independent simulators) but **impossible in Hardware mode**: a COM port can
only be opened by one process, so starting the second one fails with

    SerialConnectionError: failed to open serial port 'COM10':
    PermissionError(13, '拒绝访问。')

There is exactly one physical STM32 and one physical cable, so there must
be exactly one reader. This script is that single reader: it builds **one**
runtime (one SerialChannel, one HardwareDeviceReceiver) and attaches
**both** consumers to it.

That is not a workaround -- it is the arrangement the architecture was
designed for. ``ui/`` and ``gateway/`` are peers, both consuming
``api.ApiInterface`` and neither aware of the other
(docs/02_Architecture/Multi_Client_System_Architecture.md). Serial bytes are
decoded once, published once to ``DataService``, and fanned out to both.

Threading
---------
- **Qt main thread**: owns the QTimer that drives ``runner.run_once()``, so
  every ``DataService.publish()`` -- and therefore every UI update -- happens
  on the Qt thread, as PyQt6 requires.
- **Background thread**: uvicorn and its asyncio loop. ``EventHub.publish()``
  is explicitly documented as safe to call from any thread (it marshals via
  ``loop.call_soon_threadsafe``), which is precisely this case.

Latency: a data point reaches the phone through the same single decode, with
one extra ``call_soon_threadsafe`` hop. Nothing is polled, relayed, or
re-parsed, so this is as direct as the two-consumer fan-out can be.

Usage::

    python scripts/run_all.py                                   # simulator
    python scripts/run_all.py --mode hardware --port-serial COM10

As with run_api_server.py, ``--port`` is the HTTP port and ``--port-serial``
is the STM32's COM port -- named distinctly so they cannot be confused.
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# Also put scripts/ itself on the path. Running this file directly already
# does that implicitly, but importing it as ``scripts.run_all`` (which is how
# the test suite reaches it) does not -- and then the sibling import below
# fails with ModuleNotFoundError.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# run_api_server is imported for its composition helpers rather than copying
# their wiring: build_hardware_runtime() in particular contains the explicit
# watch_alarms_for() call whose absence was a real bug once already (see
# docs/05_Test/Project_Status_Context.md, Application Layer, 2026-08-12).
import run_api_server  # noqa: E402  (same scripts/ directory)
import uvicorn  # noqa: E402
from automation_wiring import (  # noqa: E402
    LoggingApi,
    attach_export_status,
    attach_history,
    attach_language_model,
    logging_answer_sink,
    logging_question_observer,
    make_cloud_sync_runner,
    make_cloud_view_runner,
    make_poll_once,
)
from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402
from question_log import QuestionLog  # noqa: E402  (same scripts/ directory)

from api.local_api import LocalApi  # noqa: E402
from gateway.server import (  # noqa: E402
    assistant_detail_sink,
    assistant_sink,
    create_app,
    set_question_observer,
)
from llm.ollama import DEFAULT_MODEL as DEFAULT_LLM_MODEL  # noqa: E402
from service.assistant.models import Answer  # noqa: E402
from ui.controller import MainController  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.theme import apply_theme  # noqa: E402

DEV_CLIENT_ID = "dev-gui"


def _start_gateway_thread(
    app: object, host: str, port: int
) -> tuple[uvicorn.Server, threading.Thread]:
    """Run uvicorn on a daemon thread and return it for later shutdown.

    uvicorn skips installing signal handlers when it is not on the main
    thread, so running it here does not interfere with Qt's own handling.
    """
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="gateway", daemon=True)
    thread.start()
    return server, thread


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("simulator", "hardware"), default="simulator"
    )
    parser.add_argument(
        "--port-serial", default=None, help="STM32 serial port, e.g. COM10"
    )
    parser.add_argument(
        "--baudrate", type=int, default=run_api_server.DEFAULT_SERIAL_BAUDRATE
    )
    parser.add_argument(
        "--device-id", default=run_api_server.DEFAULT_HARDWARE_DEVICE_ID
    )
    parser.add_argument("--host", default=run_api_server.DEFAULT_HTTP_HOST)
    parser.add_argument("--port", type=int, default=run_api_server.DEFAULT_HTTP_PORT)
    parser.add_argument(
        "--llm-model",
        default=DEFAULT_LLM_MODEL,
        help=f"Ollama model used to reword answers (default: {DEFAULT_LLM_MODEL})",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="skip the language model entirely; answers stay templated",
    )
    args = parser.parse_args(argv)
    if args.mode == "hardware" and not args.port_serial:
        parser.error("--mode hardware requires --port-serial, e.g. --port-serial COM10")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    if args.mode == "hardware":
        assert args.port_serial is not None  # enforced by _parse_args
        runtime, targets, runner = run_api_server.build_hardware_runtime(
            serial_port=args.port_serial,
            baudrate=args.baudrate,
            device_id=args.device_id,
        )
        mode_label = "硬件模式"
        gateway_mode = "hardware"
    else:
        runtime, targets, runner = run_api_server.build_simulator_runtime()
        mode_label = "模拟模式"
        gateway_mode = "simulator"

    # One runtime, two consumers. Each gets its own LocalApi facade (they are
    # thin and stateless); the shared state that matters -- device registry,
    # DataService, control ownership -- lives in the runtime underneath, so
    # the phone and the desktop see a consistent picture of the same device.
    gateway_app = create_app(
        LocalApi(runtime), subscriptions=targets, mode_label=gateway_mode
    )
    # Browser console at /web/ (web/README.md), same as run_api_server.py.
    run_api_server.mount_web_console(gateway_app)
    server, _thread = _start_gateway_thread(gateway_app, args.host, args.port)

    qt_app = QApplication.instance() or QApplication(sys.argv)
    assert isinstance(qt_app, QApplication)
    apply_theme(qt_app)

    # Same wiring as scripts/run_gui.py, via the shared helper -- the
    # assistant being wired in one launcher and not another is exactly the
    # drift automation_wiring.py exists to prevent.
    llm_available, llm_detail = attach_language_model(
        runtime, model=args.llm_model, enabled=not args.no_llm
    )
    if not llm_available:
        print(f"[llm] 未接入本地模型，问答只用模板：{llm_detail}")

    # 问答日志见 scripts/question_log.py；桌面与手机两端都记，靠 from 字段区分。
    question_log = QuestionLog()
    # 历史记录：与 run_gui 同一处接线，桌面与手机共用这一个库。
    history_store = attach_history(runtime)
    # 与 run_gui 同一套：助手只读台账，上传由界面按钮触发。
    export_ledger = attach_export_status(runtime)
    controller = MainController(
        LoggingApi(runtime, question_log), client_id=DEV_CLIENT_ID
    )
    window = MainWindow(controller, mode_label=mode_label)
    window.set_assistant_model_status(llm_available, llm_detail)
    window.set_cloud_sync_runner(
        make_cloud_sync_runner(window.append_activity)
    )
    window.set_cloud_view_runner(
        make_cloud_view_runner(window.append_activity)
    )
    window.resize(1280, 820)
    window.show()

    timer = QTimer()
    timer.setInterval(int(runner.poll_interval_seconds * 1000))
    # Drives run_once(), the automation dispatchers, and the assistant's
    # model polling. Connecting runner.run_once directly here is what left
    # ventilation, spoken alarms and the board's alarm-state display dead
    # in this launcher -- see scripts/automation_wiring.py's docstring.
    # Built after the controller exists, because it delivers late model
    # rephrasings straight into it.
    # One assistant, two presentation ends: the desktop panel and every
    # connected phone get the same late answer. Fanning out here rather than
    # inside the assistant keeps it unaware of who is listening -- the same
    # reason DataService publishes instead of calling consumers by name.
    to_phone = assistant_sink(gateway_app)

    def deliver_assistant_answer(text: str, source: str) -> None:
        controller.deliver_assistant_answer(text, source)
        to_phone(text, source)

    # The other direction: what the phone asked, shown on the desktop.
    # Without it the desktop saw only the *late* model answer to a question
    # nobody here typed -- an answer with no question above it -- and a fan
    # that changed mode for no visible reason.
    def note_phone_question(question: str, answer: Answer) -> None:
        applied = answer.facts is not None and answer.facts.applied is True
        controller.note_remote_question(question, answer.text, applied=applied)
        # runtime.ask() already recorded this answer as a local one; re-record
        # it with the remote tag so the board's second page says where the
        # question came from. Same payload otherwise, so nothing extra is sent.
        if runtime.answer_dispatcher is not None:
            runtime.answer_dispatcher.record(answer, remote=True)

    set_question_observer(
        gateway_app, logging_question_observer(question_log, note_phone_question)
    )

    timer.timeout.connect(
        make_poll_once(
            runtime,
            runner,
            on_assistant_answer=logging_answer_sink(
                question_log, deliver_assistant_answer
            ),
            # The trace goes only to the gateway: the web console shows it,
            # the desktop panel does not (2026-09-23).
            on_assistant_detail=assistant_detail_sink(gateway_app),
        )
    )
    runner.start()
    timer.start()

    exit_code = qt_app.exec()

    # Closing the window ends the Qt loop; tell uvicorn to stop too, so the
    # process actually exits instead of lingering on the daemon thread.
    runner.stop()
    server.should_exit = True
    # 最后一问可能还挂着等模型改写，退出前落盘。
    question_log.flush()
    runtime.history_recorder.flush()
    history_store.close()
    export_ledger.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
