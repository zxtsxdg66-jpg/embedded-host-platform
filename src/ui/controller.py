"""MainController: mediates between MainWindow (View) and api.ApiInterface.

Corresponds to .claude/skills/pyqt6-ui-development-rules: "ALWAYS use
Qt's signal/slot mechanism for UI-to-logic communication" and strict MVC
separation -- MainWindow never touches ApiInterface directly; it calls
MainController's plain methods, and MainController emits Qt signals that
MainWindow connects slots to.

This project's layering already provides the "Model" role the skill's
generic template describes (business logic, with no Qt dependencies):
that role is filled by api.ApiInterface (and everything behind it).
MainController does not reimplement any business logic -- it only adapts
ApiInterface calls and their results into Qt signals/slots, matching the
skill's ``Controller(QObject)`` pattern, and it is the only file in ui/
that imports from `api`.

UI Layer boundary: this module imports only from `api` (ApiInterface,
ApiError), `core` (id type aliases), `service.command_models`/
`service.data_models`/`service.sensor_data_processor` (the plain
dataclasses -- Command, DataPoint, ThresholdStatus, ChannelStatistics --
that flow across the api boundary as the shared concept model per
docs/02_Architecture/Core_Service_Design.md Section 8), and `PyQt6`. It
never imports `application`, `device`, `communication`, or `protocol`, and
never constructs or calls a Device/Communication/Protocol object directly.

Phase 1 runs entirely synchronously (the whole stack behind api is
in-process and synchronous, see application/manager.py's docstring), so
every method here completes immediately and no QThread is needed yet --
consistent with the Iron Law "never block the main thread", which is
trivially satisfied when there is nothing that blocks.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from api.exceptions import ApiError
from api.interface import ApiInterface
from core.models import ChannelId, ClientId, CommandType, DeviceId
from service.assistant.models import Answer, IntentKind
from service.command_models import Command
from service.data_models import DataPoint
from service.sensor_data_processor import ChannelStatistics, ThresholdStatus
from service.ventilation_controller import FanDecision, FanMode

OFFER_TAGS: dict[IntentKind, str] = {
    IntentKind.CLOUD_SYNC_HINT: "cloud_sync",
    IntentKind.CLOUD_VIEW_HINT: "cloud_view",
}
"""Intent kinds whose answers carry an offer, and the view's tag for each.

A mapping rather than "anything that is not a question", because the
default must be *no button*: every entry added here gets a clickable path
to something outside the program, and that should be a decision someone
made on purpose, one kind at a time.

It is also a **translation**, not the enum's own spelling. Emitting
``kind.value`` directly was the first version and it did not work: the
panel registers its handler under ``"cloud_sync"`` while the enum's value
is ``"cloud_sync_hint"``, so the tag arrived, matched nothing, and the
answer appeared with no button under it -- no error anywhere. Naming the
view-facing tag here makes the two ends meet in one place, and
``tests/ui/test_controller.py`` pins them together so a rename cannot
quietly unhook the button again."""


def _offer_tag(answer: Answer) -> str:
    """The action tag for ``answer``, or "" when it carries no offer.

    An offer needs something to act on, not just a kind that could have
    one. For the upload offer that means a *positive* pending count:

    - ``0`` -- everything is already up, and the answer says so. A button
      under it would do nothing and imply there was something left.
    - ``None`` -- the ledger could not be read, and the answer tells the
      user to run ``cloud_sync_导出并上传.bat`` themselves. Offering a button
      contradicts the sentence sitting directly above it.

    Both were caught by running the window rather than by a test: the
    button appeared under "我查不到还有多少没传", which reads as the
    assistant not trusting its own advice.
    """
    if answer.intent is None:
        return ""
    tag = OFFER_TAGS.get(answer.intent.kind, "")
    if not tag:
        return ""
    if answer.intent.kind is IntentKind.CLOUD_SYNC_HINT:
        pending = answer.facts.pending_uploads if answer.facts else None
        if not pending:
            return ""
    # 查看没有这个前提：云上有没有东西要连上才知道，而"什么都没有"
    # 本身也是一个值得看到的答案。
    return tag


class MainController(QObject):
    """Adapts ApiInterface calls/results into Qt signals for MainWindow."""

    devices_changed = pyqtSignal(list)
    device_status_changed = pyqtSignal(str, bool, bool, str)
    data_received = pyqtSignal(str, str, str)
    control_acquired = pyqtSignal(str, bool)
    command_result_ready = pyqtSignal(str, str, str)
    error_occurred = pyqtSignal(str)
    alarm_status_changed = pyqtSignal(str, str, float, float, str, bool)
    """device_id, channel, value, threshold, kind ("ABOVE_MAX"/"BELOW_MIN"),
    triggered -- emitted for every evaluated threshold reading, not just
    violations, so a view can also detect recovery (triggered=False)."""
    fan_decision_changed = pyqtSignal(bool, str, str)
    """should_run, reason (display text), mode name ("AUTO"/"MANUAL_ON"/
    "MANUAL_OFF") -- emitted for every evaluated reading and whenever the
    thresholds or mode change, so a view can render the fan's current
    desired state continuously rather than only on transitions."""
    remote_activity = pyqtSignal(str)
    """One line describing something a *different* client did.

    The desktop and the phone drive the same platform, and until now the
    desktop could not tell a setting it had not touched from one it had.
    The ventilation panel already follows the change itself; this says who
    caused it, which is the part a person needs when two people can turn
    the same fan on.
    """
    ventilation_settings_changed = pyqtSignal(float, float, str)
    """temperature_max, humidity_max, mode name -- emitted by
    refresh_ventilation_settings() so the view can sync its inputs to
    what the platform actually holds."""
    device_channels_changed = pyqtSignal(str, list)
    """device_id, channel ids the device declares.

    Separate from ``device_status_changed`` rather than a fifth argument
    on it, so existing connections keep working. A view uses it to offer
    only the channels the selected device actually has -- see
    DeviceStatusView.channels for the bug that made this necessary."""
    assistant_answered = pyqtSignal(str, str, str)
    """(text, source, action).

    ``action`` is the tag of an offer the answer carries -- currently only
    ``"cloud_sync"`` -- or empty, which is every answer but one. It is the
    intent kind's *value*, a plain string: the view reads a tag and never
    imports the service layer's enum, and nothing about it lets the view
    start anything on its own (see
    docs/02_Architecture/History_And_Cloud_Design.md section 6.1)."""
    """text, source ("template"/"model"/"fallback").

    ``source`` says who composed the *wording*, never who supplied the
    numbers -- those always come from the data layer. The view labels it
    so a viewer can tell a templated answer from a model-reworded one.
    """
    statistics_changed = pyqtSignal(str, str, float, float, float, float, int)

    history_loaded = pyqtSignal(str, str, list)
    """(device_id, channel, list[HistoryPoint]) —— 一次性送出既有历史。

    与 ``data_received`` 分开而不是逐条重放：预填是"开机时补上之前的"，
    逐条发几百次信号会让界面在启动瞬间刷几百遍，而它们本来就该一次画完。
    """
    """device_id, channel, current, minimum, maximum, average, sample_count
    -- emitted for every numeric DataPoint on any channel, not limited to
    temperature/humidity/noise (see ChannelStatistics/on_statistics)."""

    def __init__(self, api: ApiInterface, client_id: ClientId) -> None:
        super().__init__()
        self._api = api
        self._client_id = client_id
        self._subscription_ids: dict[tuple[DeviceId, ChannelId], str] = {}
        self._api.subscribe_alarm_status(self._handle_alarm_status)
        self._api.subscribe_statistics(self._handle_statistics)
        self._shown_ventilation: tuple[float, float, str] | None = None
        """Settings the view was last told about, so a change made
        elsewhere can be told apart from no change at all."""
        self._api.subscribe_fan_decision(self._handle_fan_decision)

    # -- device queries -------------------------------------------------

    def refresh_devices(self) -> None:
        """Fetch the current device list and emit ``devices_changed``."""
        try:
            device_ids = self._api.list_devices()
        except ApiError as exc:
            self.error_occurred.emit(str(exc))
            return
        self.devices_changed.emit(list(device_ids))

    def refresh_device_status(self, device_id: DeviceId) -> None:
        """Fetch ``device_id``'s status and emit ``device_status_changed``."""
        try:
            status = self._api.get_device_status(device_id)
        except ApiError as exc:
            self.error_occurred.emit(str(exc))
            return
        self.device_status_changed.emit(
            status.device_id,
            status.is_connected,
            status.is_occupied,
            status.occupant or "",
        )
        self.device_channels_changed.emit(status.device_id, list(status.channels))

    # -- data subscription ------------------------------------------------

    def subscribe(self, device_id: DeviceId, channel_id: ChannelId) -> None:
        """Subscribe to data on device_id/channel_id; delivery arrives via
        ``data_received``."""
        try:
            subscription_id = self._api.subscribe_data(
                device_id, channel_id, self._handle_data_point
            )
        except ApiError as exc:
            self.error_occurred.emit(str(exc))
            return
        self._subscription_ids[(device_id, channel_id)] = subscription_id

    def unsubscribe(self, device_id: DeviceId, channel_id: ChannelId) -> None:
        subscription_id = self._subscription_ids.pop((device_id, channel_id), None)
        if subscription_id is not None:
            self._api.unsubscribe_data(subscription_id)

    def _handle_data_point(self, point: DataPoint) -> None:
        """Callback registered with the API's data subscription; runs
        synchronously on whatever call triggered publication (see module
        docstring), then re-expresses the point as a Qt signal."""
        self.data_received.emit(point.device_id, point.channel, str(point.value))

    def _handle_alarm_status(self, status: ThresholdStatus) -> None:
        """Callback registered once (in __init__) with the API's global
        alarm-status subscription; runs synchronously, same as
        _handle_data_point."""
        self.alarm_status_changed.emit(
            status.device_id,
            status.channel,
            status.value,
            status.threshold,
            status.kind.name,
            status.triggered,
        )

    def _handle_statistics(
        self, device_id: DeviceId, channel: ChannelId, stats: ChannelStatistics
    ) -> None:
        """Callback registered once (in __init__) with the API's global
        statistics subscription; runs synchronously, same as
        _handle_data_point."""
        self.statistics_changed.emit(
            device_id,
            channel,
            stats.current,
            stats.minimum,
            stats.maximum,
            stats.average,
            stats.sample_count,
        )

    # -- ventilation ------------------------------------------------------

    def _handle_fan_decision(self, decision: FanDecision) -> None:
        """Callback registered once (in __init__) with the API's global
        fan-decision subscription; runs synchronously, same as
        _handle_data_point.

        The mode crosses into the view as its plain ``name`` string rather
        than the FanMode enum: ui/widgets/* must not import ``service``
        (see ui/README.md), and a signal carrying an enum would force them
        to.
        """
        self.fan_decision_changed.emit(
            decision.should_run, decision.reason, decision.mode.name
        )
        # Fan decisions arrive on every reading, from whatever changed the
        # settings -- which makes this the one place that notices a change
        # no user of *this* screen made.
        self._sync_ventilation_settings()

    def note_remote_question(self, question: str, text: str, applied: bool) -> None:
        """Record that another client asked -- or instructed -- something.

        Pushed in by the composition root, like
        :meth:`deliver_assistant_answer`: the controller has no way to
        watch the gateway, and giving it one would mean the desktop knew a
        gateway existed.

        Instructions and questions are labelled differently on purpose. A
        question from the phone is context; an instruction from the phone
        changed this system's behaviour, and that is the line someone will
        be looking for when they wonder why the fan came on.
        """
        label = "移动端下发" if applied else "移动端提问"
        self.remote_activity.emit(f"{label}：{question} → {text}")

    def refresh_ventilation_settings(self) -> None:
        """Fetch the current ventilation settings and emit
        ``ventilation_settings_changed``, so the view can show what the
        platform actually holds instead of its own defaults."""
        self._shown_ventilation = self._read_ventilation_settings()
        self.ventilation_settings_changed.emit(*self._shown_ventilation)

    def _read_ventilation_settings(self) -> tuple[float, float, str]:
        settings = self._api.get_ventilation_settings()
        return (settings.temperature_max, settings.humidity_max, settings.mode.name)

    def _sync_ventilation_settings(self) -> None:
        """Emit the ventilation settings, but only when they have actually
        moved since the view was last told.

        This is what makes a change made *somewhere else* show up here.
        The phone is the case that motivated it: a client asking the
        gateway to turn the fan on changes the same VentilationController
        the panel edits, and until 2026-09-08 the PC went on displaying
        「自动」 next to a fan card already reading 「手动常开」 -- two
        widgets on one screen disagreeing about the same setting.

        Emitting only on a real change is the whole point, not an
        optimisation: this runs on every reading, and writing the
        spin-boxes unconditionally would overwrite a threshold the user is
        halfway through typing.
        """
        settings = self._read_ventilation_settings()
        if settings == self._shown_ventilation:
            return
        self._shown_ventilation = settings
        self.ventilation_settings_changed.emit(*settings)

    def set_ventilation_thresholds(
        self, temperature_max: float, humidity_max: float
    ) -> None:
        """Apply new ventilation thresholds. These are not the alarm
        thresholds, which stay fixed -- see
        service.ventilation_controller."""
        self._api.set_ventilation_thresholds(temperature_max, humidity_max)

    def set_fan_mode(self, mode_name: str) -> None:
        """Apply a fan mode given by name (``"AUTO"``/``"MANUAL_ON"``/
        ``"MANUAL_OFF"``).

        Takes a string, not a FanMode, so the view never has to construct
        a ``service`` type; invalid names are reported through
        ``error_occurred`` rather than raising into the Qt signal that
        delivered them.
        """
        try:
            mode = FanMode[mode_name]
        except KeyError:
            self.error_occurred.emit(f"未知的风扇模式：{mode_name}")
            return
        self._api.set_fan_mode(mode)

    # -- control -------------------------------------------------------

    def acquire_control(self, device_id: DeviceId) -> None:
        try:
            acquired = self._api.acquire_control(device_id, self._client_id)
        except ApiError as exc:
            self.error_occurred.emit(str(exc))
            return
        self.control_acquired.emit(device_id, acquired)
        self.refresh_device_status(device_id)

    def release_control(self, device_id: DeviceId) -> None:
        try:
            self._api.release_control(device_id, self._client_id)
        except ApiError as exc:
            self.error_occurred.emit(str(exc))
            return
        self.refresh_device_status(device_id)

    def submit_command(self, device_id: DeviceId, command_type: CommandType) -> None:
        command = Command(
            device_id=device_id, command_type=command_type, origin=self._client_id
        )
        try:
            result = self._api.submit_command(command)
        except ApiError as exc:
            self.error_occurred.emit(str(exc))
            return
        self.command_result_ready.emit(
            result.command_id, result.status.name, result.message
        )

    # -- environment assistant ------------------------------------------

    # A ventilation refresh follows every answer, in both paths below.
    # An instruction ("把风扇打开", "通风阈值调到 28 度") changes the same
    # settings the ventilation panel edits, so without this the panel would
    # keep showing what the user last clicked rather than what is in force.
    # Refreshing unconditionally rather than only for control answers keeps
    # the composition root out of it: the alternative is threading the
    # intent kind through ``deliver_assistant_answer``, which widens a
    # cross-layer signature to save one property read.

    def ask(self, question: str) -> None:
        """Answer ``question`` and emit ``assistant_answered``.

        Synchronous, and safe to call straight from a button press: the
        rule/template path is pure computation with no I/O. If a model is
        attached it is *not* waited for here -- the template answer is
        emitted immediately and any rephrasing arrives later through the
        poll loop, so the UI never blocks on generation.
        """
        text = question.strip()
        if not text:
            return
        try:
            answer = self._api.ask(text)
        except ApiError as exc:
            self.error_occurred.emit(str(exc))
            return
        self.assistant_answered.emit(
            answer.text, answer.source.value, _offer_tag(answer)
        )
        self.refresh_ventilation_settings()

    def load_history(
        self, device_id: DeviceId, channel_id: ChannelId, limit: int = 500
    ) -> None:
        """Fetch stored readings for one channel and emit ``history_loaded``.

        Lives here rather than in the widget because ``ui/widgets/`` may
        not reach the platform: presentation talks to ``api`` only through
        this controller. The widget stays a view that is handed values.

        Failure is reported the same way every other query here reports
        it -- through ``error_occurred`` -- rather than raising: history
        being unavailable must not stop the window from opening.
        """
        try:
            points = self._api.query_history(device_id, channel_id, limit=limit)
        except ApiError as exc:
            self.error_occurred.emit(str(exc))
            return
        self.history_loaded.emit(device_id, channel_id, points)

    def deliver_assistant_answer(self, text: str, source: str) -> None:
        """Emit a late answer produced outside a direct :meth:`ask` call.

        Used for a language model's rephrasing, which lands seconds after
        the template answer already shown. Takes plain strings and is
        pushed in by the composition root -- the controller has no way to
        poll the model itself, and giving it one would mean widening
        ApiInterface for something only the launcher needs to know about.
        """
        # No tag: a late rephrasing rewrites the wording of an answer
        # whose button, if it had one, is already on screen. Re-sending the
        # tag would be harmless today (the bubble refuses a second button)
        # but it would be saying something this path cannot actually know.
        self.assistant_answered.emit(text, source, "")
        self.refresh_ventilation_settings()
