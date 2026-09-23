"""FastAPI application exposing ApiInterface over REST + WebSocket.

Endpoints implemented (phase 1) -- every one is a thin translation of an
ApiInterface method that already existed; none of them required changing
api/, service/, or application/:

  GET  /health                                  -- liveness + mode label
  GET  /devices                                 -- ApiInterface.list_devices
  GET  /devices/{device_id}/status              -- ApiInterface.get_device_status
  POST /devices/{device_id}/control/acquire     -- ApiInterface.acquire_control
  POST /devices/{device_id}/control/release     -- ApiInterface.release_control
  POST /devices/{device_id}/commands            -- ApiInterface.submit_command
  GET  /devices/{device_id}/commands/{cmd_id}   -- ApiInterface.get_command_result
  GET  /devices/{id}/channels/{channel}/history -- ApiInterface.query_history
  POST /assistant/ask                           -- ApiInterface.ask
  GET  /ventilation                             -- ApiInterface.get_ventilation_settings
  PUT  /ventilation/thresholds  -- ApiInterface.set_ventilation_thresholds
  PUT  /ventilation/mode                        -- ApiInterface.set_fan_mode
  GET  /link/statistics                         -- ApiInterface.get_link_statistics
  WS   /ws  -- data / alarm_status / statistics / assistant / fan_decision /
              assistant_detail / link_event

Ventilation, added 2026-09-23 for the web console
(docs/02_Architecture/Web_Console_Design.md section 4). Same kind of thin
translation as history: the four ApiInterface methods existed since the
ventilation feature landed; only this server had not exposed them.

History, added 2026-09-17. It used to be listed here as *deliberately not
implemented*, and that note is kept rather than deleted because the
decision it recorded was real: PC-side history existed only inside
ui/widgets/data_panel.py's QTableWidget, service/application/api had no
history capability, and this server would not reach into a widget to fake
one. What changed is the premise, not the principle -- history is now a
capability of the platform itself (``ApiInterface.query_history``), so
this endpoint is the same thin translation every other one here is. See
docs/02_Architecture/History_And_Cloud_Design.md section 0.

CORS is enabled permissively because the only clients are on the user's
own LAN (phone + PC on the same Wi-Fi/hotspot) and there is no
authentication or sensitive data in this phase; see the note in
docs/10_AndroidClient/第一阶段测试流程.md before exposing this beyond a
trusted network.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.exceptions import ApiError, DeviceNotFoundError
from api.interface import ApiInterface
from core.timestamps import from_iso8601
from gateway.channel_units import channel_unit
from gateway.event_hub import EventHub
from gateway.events import (
    alarm_status_message,
    answer_detail,
    assistant_answer_message,
    assistant_detail_message,
    data_point_message,
    fan_decision_message,
    isoformat_or_none,
    link_event_message,
    link_statistics_payload,
    statistics_message,
    ventilation_payload,
)
from service.assistant.models import Answer
from service.command_models import Command
from service.ventilation_controller import FanDecision, FanMode

DEFAULT_CLIENT_ID = "android-client"


class AcquireRequest(BaseModel):
    """Body of POST /devices/{device_id}/control/acquire|release."""

    client_id: str = DEFAULT_CLIENT_ID


class CommandRequest(BaseModel):
    """Body of POST /devices/{device_id}/commands."""

    command_type: str
    parameters: dict[str, Any] = {}
    client_id: str = DEFAULT_CLIENT_ID


class AskRequest(BaseModel):
    """Body of POST /assistant/ask."""

    question: str


class ThresholdsRequest(BaseModel):
    """Body of PUT /ventilation/thresholds. A field left out stays unchanged."""

    temperature_max: float | None = None
    humidity_max: float | None = None


class ModeRequest(BaseModel):
    """Body of PUT /ventilation/mode: a :class:`FanMode` member name."""

    mode: str


def _command_result_payload(result: Any) -> dict[str, Any]:
    """Serialize a CommandResult; fields taken from service.command_models."""
    return {
        "command_id": result.command_id,
        "status": result.status.name,
        "message": result.message,
        "completed_at": (
            None if result.completed_at is None else result.completed_at.isoformat()
        ),
    }


QuestionObserver = Callable[[str, Answer], None]
"""Told about each answered question: the words asked, and the answer.

Deliberately the whole :class:`Answer` and not a formatted line -- whether
an instruction was actually carried out is in ``facts.applied``, and the
observer is what decides how to say so. Composing the sentence here would
put presentation in the gateway.
"""


def create_app(
    api: ApiInterface,
    subscriptions: list[tuple[str, str]],
    mode_label: str = "simulator",
    on_question: QuestionObserver | None = None,
) -> FastAPI:
    """Build the FastAPI app around an existing ApiInterface.

    ``subscriptions`` is the list of (device_id, channel_id) pairs the
    server subscribes to on startup so their data reaches WebSocket
    clients. It is passed in rather than discovered, because which
    channels exist is a composition decision belonging to the launcher
    script -- the same reasoning as SimulatorRuntimeRunner's targets.

    ``on_question`` is told about every question this server answers, and
    exists because the phone can change settings the desktop also shows.
    The gateway does not know a desktop exists -- it hands the fact to
    whoever assembled the two, exactly as the late-answer sink does. Left
    out (as the headless launcher leaves it), nothing observes and nothing
    changes. It can also be attached afterwards with
    :func:`set_question_observer`, which is what a launcher building the
    server before the desktop window needs.
    """
    hub = EventHub()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Bind the running loop so EventHub.publish() (called from the
        # data-pipeline thread) knows where to marshal messages to.
        hub.bind_loop(asyncio.get_running_loop())
        yield

    app = FastAPI(
        title="Embedded Host Platform Gateway", version="0.1.0", lifespan=lifespan
    )
    app.state.on_question = on_question
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.hub = hub
    app.state.api = api
    app.state.mode_label = mode_label

    # -- ApiInterface subscriptions -> EventHub ------------------------
    # These callbacks run synchronously on the publishing thread; publish()
    # is thread-safe and never raises back into the pipeline.
    for device_id, channel_id in subscriptions:
        api.subscribe_data(
            device_id,
            channel_id,
            lambda point: hub.publish(data_point_message(point)),
        )
    api.subscribe_alarm_status(lambda status: hub.publish(alarm_status_message(status)))
    api.subscribe_statistics(
        lambda device_id, channel, stats: hub.publish(
            statistics_message(device_id, channel, stats)
        )
    )

    # The latest decision is kept so GET /ventilation can say what the fan
    # is doing *now*: a client that connects between two readings would
    # otherwise see settings but no state until the next reading arrives.
    latest_decision: list[FanDecision] = []

    def on_fan_decision(decision: FanDecision) -> None:
        latest_decision[:] = [decision]
        hub.publish(fan_decision_message(decision))

    api.subscribe_fan_decision(on_fan_decision)
    api.subscribe_link_events(lambda event: hub.publish(link_event_message(event)))

    # -- REST ----------------------------------------------------------

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": mode_label,
            "websocket_subscribers": hub.subscriber_count,
            "published_count": hub.published_count,
            "dropped_count": hub.dropped_count,
        }

    @app.get("/devices")
    def list_devices() -> dict[str, Any]:
        return {"devices": api.list_devices()}

    @app.get("/devices/{device_id}/status")
    def device_status(device_id: str) -> dict[str, Any]:
        try:
            status = api.get_device_status(device_id)
        except DeviceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "device_id": status.device_id,
            "is_connected": status.is_connected,
            "is_occupied": status.is_occupied,
            "occupant": status.occupant,
        }

    @app.post("/devices/{device_id}/control/acquire")
    def acquire(device_id: str, body: AcquireRequest) -> dict[str, Any]:
        try:
            acquired = api.acquire_control(device_id, body.client_id)
        except DeviceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"acquired": acquired}

    @app.post("/devices/{device_id}/control/release")
    def release(device_id: str, body: AcquireRequest) -> dict[str, Any]:
        try:
            api.release_control(device_id, body.client_id)
        except DeviceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"released": True}

    @app.post("/devices/{device_id}/commands")
    def submit_command(device_id: str, body: CommandRequest) -> dict[str, Any]:
        command = Command(
            device_id=device_id,
            command_type=body.command_type,
            origin=body.client_id,
            parameters=body.parameters,
        )
        try:
            result = api.submit_command(command)
        except DeviceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ApiError as exc:
            # Covers CommandAuthorityError (no control acquired) and
            # CommandDeliveryError (device did not acknowledge in time).
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _command_result_payload(result)

    @app.get("/devices/{device_id}/commands/{command_id}")
    def command_result(device_id: str, command_id: str) -> dict[str, Any]:
        try:
            result = api.get_command_result(command_id)
        except ApiError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _command_result_payload(result)

    @app.get("/devices/{device_id}/channels/{channel}/history")
    def channel_history(
        device_id: str,
        channel: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Stored readings for one channel, newest first.

        ``start``/``end`` are ISO-8601 strings; a malformed one is a 400
        rather than a silent full-range query, because "I asked for last
        hour and got everything" is the kind of wrong answer a client
        cannot detect. An unknown device or channel is not an error -- it
        is an empty list, matching LocalApi.query_history's contract.

        ``unit`` sits at the top level, not on every point: it is a
        property of the channel, not of a reading, and repeating it 500
        times would say nothing extra. Point fields follow the contract
        drafted in docs/10_AndroidClient/PC_Android_接口设计.md 2.3.
        """
        try:
            start_at = from_iso8601(start) if start else None
            end_at = from_iso8601(end) if end else None
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid timestamp: {exc}"
            ) from exc
        points = api.query_history(device_id, channel, start_at, end_at, limit)
        return {
            "device_id": device_id,
            "channel": channel,
            "unit": channel_unit(channel),
            "points": [
                {
                    "value": point.value,
                    "timestamp": isoformat_or_none(point.timestamp),
                    "valid": point.valid,
                }
                for point in points
            ],
        }

    @app.post("/assistant/ask")
    def ask(body: AskRequest) -> dict[str, Any]:
        """Answer one question. Returns immediately, like the desktop panel.

        ``ApiInterface.ask`` is synchronous and never waits on a language
        model: the reply here is the rule-and-template answer, available in
        milliseconds. If a model is attached it may produce a better wording
        (or understand a question the rules missed) seconds later; that
        arrives over the WebSocket as a ``type: "assistant"`` message rather
        than by holding this request open. A client that only calls REST
        still gets a correct answer -- it just never sees the improved one.

        An empty question is rejected rather than answered: the assistant
        would return its help text, which is a fine answer to "what can you
        do" but a confusing one to a request that carried nothing.
        """
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="question must not be empty")
        answer = api.ask(question)
        # Read at call time, not captured: the observer may be attached
        # after this app was built (see set_question_observer).
        observer: QuestionObserver | None = getattr(app.state, "on_question", None)
        if observer is not None:
            observer(question, answer)
        # intent/facts/trace added 2026-09-23 for the web console; the phone
        # reads text/source as before and ignores the rest.
        return {
            "text": answer.text,
            "source": answer.source.value,
            **answer_detail(answer),
        }

    # -- ventilation ----------------------------------------------------

    @app.get("/ventilation")
    def ventilation() -> dict[str, Any]:
        decision = latest_decision[0] if latest_decision else None
        return ventilation_payload(api.get_ventilation_settings(), decision)

    @app.put("/ventilation/thresholds")
    def set_thresholds(body: ThresholdsRequest) -> dict[str, Any]:
        """Change either or both thresholds; the reply is the new settings.

        Only non-finite values are refused here. What range is sensible
        depends on the sensor and the site, which this generic gateway does
        not know -- the same reason the controller itself has no bounds.
        """
        values = (body.temperature_max, body.humidity_max)
        if all(v is None for v in values):
            raise HTTPException(status_code=400, detail="no threshold given")
        if any(v is not None and not math.isfinite(v) for v in values):
            raise HTTPException(
                status_code=400, detail="threshold must be a finite number"
            )
        api.set_ventilation_thresholds(body.temperature_max, body.humidity_max)
        return ventilation()

    @app.put("/ventilation/mode")
    def set_mode(body: ModeRequest) -> dict[str, Any]:
        try:
            mode = FanMode[body.mode]
        except KeyError as exc:
            names = ", ".join(m.name for m in FanMode)
            raise HTTPException(
                status_code=400,
                detail=f"unknown mode {body.mode!r}; expected one of {names}",
            ) from exc
        api.set_fan_mode(mode)
        return ventilation()

    # -- link ------------------------------------------------------------

    @app.get("/link/statistics")
    def link_statistics() -> dict[str, Any]:
        return link_statistics_payload(api.get_link_statistics())

    # -- WebSocket ------------------------------------------------------

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        queue = hub.subscribe()
        try:
            while True:
                message = await queue.get()
                await websocket.send_json(message)
        except WebSocketDisconnect:
            pass
        except Exception:
            # Any send failure (client vanished, network dropped) ends this
            # connection only; other clients and the data pipeline are
            # unaffected.
            pass
        finally:
            hub.unsubscribe(queue)

    return app


def set_question_observer(app: FastAPI, observer: QuestionObserver) -> None:
    """Attach (or replace) the observer told about answered questions.

    Exists for the order launchers actually build things in: the desktop
    controller that wants to hear about phone questions is created after
    the server it would hear them from.
    """
    app.state.on_question = observer


def assistant_sink(app: FastAPI) -> Callable[[str, str], None]:
    """Build the callback that pushes late assistant answers to WS clients.

    Shape matches ``automation_wiring.make_poll_once``'s ``on_assistant_answer``
    parameter -- ``(text, source)`` -- so a launcher can hand this straight to
    it, and can fan out to both the desktop controller and the phone by
    calling the two sinks in one lambda.

    Exists so launchers do not have to reach into ``app.state.hub``: which
    object carries the WebSocket fan-out is this package's business.
    """
    hub: EventHub = app.state.hub

    def publish(text: str, source: str) -> None:
        hub.publish(assistant_answer_message(text, source))

    return publish


def assistant_detail_sink(app: FastAPI) -> Callable[[Answer], None]:
    """Build the callback that pushes a late answer's trace to WS clients.

    The companion of :func:`assistant_sink`, taking the whole Answer
    because the trace lives on it. Kept separate rather than changing
    ``assistant_sink``'s ``(text, source)`` shape, which the desktop
    controller's sink shares.
    """
    hub: EventHub = app.state.hub

    def publish(answer: Answer) -> None:
        hub.publish(assistant_detail_message(answer))

    return publish

