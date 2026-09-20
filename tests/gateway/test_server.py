"""Tests for gateway.server -- REST endpoints and the WebSocket bridge.

Uses FastAPI's TestClient, which runs the real ASGI app (real routing,
real serialization, real WebSocket handshake) in-process, against a real
ApplicationRuntime + LocalApi composed exactly the way
scripts/run_api_server.py composes them -- no mocking of the API layer.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.local_api import LocalApi
from application.runtime import ApplicationRuntime
from application.simulator_runner import SimulatorRuntimeRunner
from communication.loopback import LoopbackChannel
from device.sensors.channels import TEMPERATURE_CHANNEL
from device.sensors.temperature import TemperatureSensorSimulator
from gateway.server import assistant_sink, create_app

DEVICE_ID = "sim-temp"


@pytest.fixture
def runtime() -> ApplicationRuntime:
    runtime = ApplicationRuntime()
    device = TemperatureSensorSimulator(device_id=DEVICE_ID)
    runtime.register_device(device, LoopbackChannel(), accepted_commands=("PING",))
    return runtime


@pytest.fixture
def client(runtime: ApplicationRuntime) -> Iterator[TestClient]:
    app = create_app(
        LocalApi(runtime),
        subscriptions=[(DEVICE_ID, TEMPERATURE_CHANNEL)],
        mode_label="test",
    )
    with TestClient(app) as test_client:
        yield test_client


# -- REST --------------------------------------------------------------


def test_health_reports_mode(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["mode"] == "test"


def test_list_devices_returns_registered_device(client: TestClient) -> None:
    response = client.get("/devices")

    assert response.status_code == 200
    assert response.json() == {"devices": [DEVICE_ID]}


def test_device_status_returns_status_view_fields(client: TestClient) -> None:
    response = client.get(f"/devices/{DEVICE_ID}/status")

    assert response.status_code == 200
    body = response.json()
    assert body["device_id"] == DEVICE_ID
    assert body["is_connected"] is True
    assert body["is_occupied"] is False
    assert body["occupant"] is None


def test_unknown_device_status_returns_404(client: TestClient) -> None:
    response = client.get("/devices/does-not-exist/status")

    assert response.status_code == 404


def test_command_without_control_authority_returns_409(client: TestClient) -> None:
    """The "共享读、独占写" rule must surface as a real HTTP error, not a
    silent failure -- see service/control_service_impl.py."""
    response = client.post(
        f"/devices/{DEVICE_ID}/commands", json={"command_type": "PING"}
    )

    assert response.status_code == 409


def test_acquire_then_command_succeeds(client: TestClient) -> None:
    acquire = client.post(
        f"/devices/{DEVICE_ID}/control/acquire", json={"client_id": "tester"}
    )
    assert acquire.status_code == 200
    assert acquire.json() == {"acquired": True}

    command = client.post(
        f"/devices/{DEVICE_ID}/commands",
        json={"command_type": "PING", "client_id": "tester"},
    )

    assert command.status_code == 200
    assert command.json()["status"] == "SUCCESS"
    assert command.json()["command_id"]


def test_release_control_succeeds(client: TestClient) -> None:
    client.post(f"/devices/{DEVICE_ID}/control/acquire", json={"client_id": "tester"})

    response = client.post(
        f"/devices/{DEVICE_ID}/control/release", json={"client_id": "tester"}
    )

    assert response.status_code == 200


def test_history_endpoint_exists_and_is_empty_without_a_store(
    client: TestClient,
) -> None:
    """替换掉原来的 `test_history_endpoint_is_absent`（留痕，不静默删除）。

    原用例断言该端点返回 404，把"阶段一故意不做历史"这个决定钉住：
    当时 PC 侧历史只存在于 PyQt6 表格控件内部，网关不该伸手去读它。
    **那个决定于 2026-09-17 撤销**——历史已成为平台自身的能力
    （`ApiInterface.query_history`），端点因此和其它七个一样只是薄转调。
    原则没变，变的是前提：网关仍然不碰任何界面控件的内部状态。

    这套 fixture 没挂存储，于是走 `NullHistoryStore`：端点存在（200），
    内容为空。"没有数据"是正常答案，不是错误。
    """
    response = client.get(f"/devices/{DEVICE_ID}/channels/temperature/history")

    assert response.status_code == 200
    body = response.json()
    assert body["device_id"] == DEVICE_ID
    assert body["channel"] == "temperature"
    assert body["points"] == []


def test_history_endpoint_returns_stored_readings(
    runtime: ApplicationRuntime,
) -> None:
    """挂上存储后端点返回真实数据，且 unit 在顶层而非逐点重复。"""
    from service.history import InMemoryHistoryStore

    runtime.attach_history(InMemoryHistoryStore())
    app = create_app(
        LocalApi(runtime),
        subscriptions=[(DEVICE_ID, TEMPERATURE_CHANNEL)],
        mode_label="test",
    )
    with TestClient(app) as client:
        runtime.report_data(DEVICE_ID, TEMPERATURE_CHANNEL)
        runtime.history_recorder.flush()

        body = client.get(
            f"/devices/{DEVICE_ID}/channels/{TEMPERATURE_CHANNEL}/history"
        ).json()

    assert body["unit"] == "°C"
    assert len(body["points"]) == 1
    point = body["points"][0]
    assert set(point) == {"value", "timestamp", "valid"}
    assert point["valid"] is True


def test_history_endpoint_rejects_a_malformed_timestamp(
    client: TestClient,
) -> None:
    """坏时间戳给 400，而不是悄悄退化成全量查询。

    "我要最近一小时，拿回了全部"是客户端察觉不到的错答案。
    """
    response = client.get(
        f"/devices/{DEVICE_ID}/channels/temperature/history",
        params={"start": "昨天"},
    )

    assert response.status_code == 400


def test_history_endpoint_passes_the_limit_through(
    runtime: ApplicationRuntime,
) -> None:
    from service.history import InMemoryHistoryStore

    runtime.attach_history(InMemoryHistoryStore())
    app = create_app(
        LocalApi(runtime),
        subscriptions=[(DEVICE_ID, TEMPERATURE_CHANNEL)],
        mode_label="test",
    )
    with TestClient(app) as client:
        for _ in range(5):
            runtime.report_data(DEVICE_ID, TEMPERATURE_CHANNEL)
        runtime.history_recorder.flush()

        body = client.get(
            f"/devices/{DEVICE_ID}/channels/{TEMPERATURE_CHANNEL}/history",
            params={"limit": 2},
        ).json()

    assert len(body["points"]) == 2


def test_history_endpoint_for_an_unknown_channel_is_empty_not_404(
    client: TestClient,
) -> None:
    """未知通道返回空列表，与 LocalApi.query_history 的约定一致：
    呈现端是在确认"这儿有没有数据"，空就是答案。"""
    response = client.get(f"/devices/{DEVICE_ID}/channels/nope/history")

    assert response.status_code == 200
    assert response.json()["points"] == []


# -- WebSocket ---------------------------------------------------------


def test_websocket_receives_published_data_point(
    client: TestClient, runtime: ApplicationRuntime
) -> None:
    """End-to-end: generating a data point through the real runtime must
    reach a connected WebSocket client.

    Does not assume the "data" message arrives first: one report_data()
    call fans out to three independent subscribers (the gateway's data
    subscription plus the runtime's own alarm/statistics processor), and
    their relative order is a function of subscription order, not part of
    the wire contract.
    """
    with client.websocket_connect("/ws") as websocket:
        runner = SimulatorRuntimeRunner(runtime, [(DEVICE_ID, TEMPERATURE_CHANNEL)])
        runner.run_once()

        messages = [websocket.receive_json() for _ in range(3)]

    data_messages = [m for m in messages if m["type"] == "data"]
    assert len(data_messages) == 1
    message = data_messages[0]
    assert message["device_id"] == DEVICE_ID
    assert message["channel"] == TEMPERATURE_CHANNEL
    assert message["unit"] == "°C"
    assert isinstance(message["value"], float)


def test_websocket_receives_statistics_and_alarm_status(
    client: TestClient, runtime: ApplicationRuntime
) -> None:
    """All three message types must reach the client from one data point:
    the data itself, its statistics snapshot, and its threshold status."""
    with client.websocket_connect("/ws") as websocket:
        runner = SimulatorRuntimeRunner(runtime, [(DEVICE_ID, TEMPERATURE_CHANNEL)])
        runner.run_once()

        types = {websocket.receive_json()["type"] for _ in range(3)}

    assert types == {"data", "statistics", "alarm_status"}


def test_websocket_disconnect_is_clean(
    client: TestClient, runtime: ApplicationRuntime
) -> None:
    """A client dropping must not break the server or later publications."""
    with client.websocket_connect("/ws"):
        pass  # disconnect immediately

    runner = SimulatorRuntimeRunner(runtime, [(DEVICE_ID, TEMPERATURE_CHANNEL)])
    runner.run_once()  # must not raise now that the subscriber is gone

    assert client.get("/health").status_code == 200

# -- assistant ---------------------------------------------------------


def test_ask_returns_an_answer_immediately(client: TestClient) -> None:
    """The REST reply is the rule-and-template answer, produced without
    waiting on any language model -- the phone gets a usable answer in the
    same request, exactly as the desktop panel does."""
    response = client.post("/assistant/ask", json={"question": "有几个设备在线"})

    assert response.status_code == 200
    body = response.json()
    assert DEVICE_ID in body["text"]
    assert body["source"] == "template"


def test_ask_falls_back_instead_of_guessing(client: TestClient) -> None:
    """An unrecognised question yields the capability list, not a guess."""
    response = client.post("/assistant/ask", json={"question": "帮我订张票"})

    assert response.status_code == 200
    assert response.json()["source"] == "fallback"


def test_empty_question_is_rejected(client: TestClient) -> None:
    """Answering an empty request with the help text would read as though
    the client had asked "what can you do", which it did not."""
    response = client.post("/assistant/ask", json={"question": "   "})

    assert response.status_code == 400


def test_late_assistant_answer_reaches_websocket_clients(client: TestClient) -> None:
    """A model answer arrives seconds after the REST reply, so it travels on
    the WebSocket. This is the path scripts wire through assistant_sink."""
    sink = assistant_sink(client.app)  # type: ignore[arg-type]

    with client.websocket_connect("/ws") as websocket:
        sink("噪声现在是 40.5dB。", "model")
        message = websocket.receive_json()

    assert message == {
        "type": "assistant",
        "text": "噪声现在是 40.5dB。",
        "source": "model",
    }


def test_assistant_sink_never_raises_into_the_poll_loop(
    runtime: ApplicationRuntime,
) -> None:
    """The sink is called from the polling thread that also drives the data
    pipeline. With no event loop bound (app never started), publishing must
    be a no-op rather than an exception."""
    app = create_app(LocalApi(runtime), subscriptions=[], mode_label="test")

    assistant_sink(app)("任何文本", "template")  # must not raise


# -- 谁问的，本机要看得见 -----------------------------------------------------


def test_an_answered_question_is_reported_to_the_observer(
    runtime: ApplicationRuntime,
) -> None:
    """手机改的是 PC 进程里同一套设置。网关不知道有没有桌面端，
    它只把"发生了什么"交出去，由组装两者的人决定怎么用。"""
    from gateway.server import set_question_observer

    app = create_app(
        LocalApi(runtime),
        subscriptions=[(DEVICE_ID, TEMPERATURE_CHANNEL)],
        mode_label="test",
    )
    seen: list[tuple[str, str]] = []
    set_question_observer(app, lambda q, a: seen.append((q, a.text)))

    with TestClient(app) as client:
        client.post("/assistant/ask", json={"question": "现在噪声多少"})

    assert len(seen) == 1
    assert seen[0][0] == "现在噪声多少"
    assert seen[0][1]


def test_no_observer_changes_nothing(runtime: ApplicationRuntime) -> None:
    """无界面启动器不挂观察者，这条路径必须照常工作。"""
    app = create_app(
        LocalApi(runtime),
        subscriptions=[(DEVICE_ID, TEMPERATURE_CHANNEL)],
        mode_label="test",
    )

    with TestClient(app) as client:
        response = client.post("/assistant/ask", json={"question": "现在噪声多少"})

    assert response.status_code == 200
    assert response.json()["text"]


def test_a_rejected_question_is_not_reported(
    runtime: ApplicationRuntime,
) -> None:
    """空问句根本没被回答，记一笔只会在日志里留下一条无中生有的提问。"""
    from gateway.server import set_question_observer

    app = create_app(
        LocalApi(runtime),
        subscriptions=[(DEVICE_ID, TEMPERATURE_CHANNEL)],
        mode_label="test",
    )
    seen: list[str] = []
    set_question_observer(app, lambda q, a: seen.append(q))

    with TestClient(app) as client:
        client.post("/assistant/ask", json={"question": "   "})

    assert seen == []
