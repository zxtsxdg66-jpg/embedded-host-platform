"""ApplicationRuntime: composition root for both Simulator- and Hardware-mode
data/control loops.

Corresponds to docs/02_Architecture/System_Architecture.md's layered data
flow and docs/02_Architecture/Core_Service_Design.md Section 4 (Service
Layer responsibilities). Supports two device modes side by side, per
docs/05_Test/Hardware_Simulation_Mode.md:

    Simulator mode:  SimulatorDevice + LoopbackChannel + Protocol
    Hardware mode:   RemoteDevice    + SerialChannel    + Protocol

-- see Core_Service_Design.md Section 6.2 for why the Simulator substitution
is architecturally sound: a simulator is meant to be indistinguishable from
a real device at the interface level, which is exactly what lets both
modes share every line of code below register_device().

    UI/Presentation (not implemented here)
            |
    ApplicationRuntime  <-- this module: composition + a thin facade
            |
    DeviceManager (application/manager.py) --- InMemoryControlService (service/)
            |                                          |
    protocol.encode/decode                    CommandTransport contract
            |                                          |
    CommunicationChannel (communication/) <-------------
            |
    SimulatorDevice or RemoteDevice (device/)

Not a UI: this module contains no PyQt/Android code -- it is what a future
UI or api/ layer would sit on top of. Not bound to any specific sensor,
controlled object, or MCU model.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from application.alarm_state_dispatcher import AlarmStateDispatcher
from application.alert_dispatcher import AlertCommandDispatcher
from application.answer_dispatcher import AnswerDispatcher
from application.fan_dispatcher import FanCommandDispatcher
from application.history_recorder import HistoryRecorder
from application.manager import DeviceManager
from communication.interface import CommunicationChannel
from core.models import ChannelId, ClientId, CommandType, DeviceId
from device.interface import DeviceInterface
from device.state import ConnectionState
from service.alarm_announcer import AlarmAnnouncer, AnnouncementCallback
from service.assistant.assistant import Assistant
from service.assistant.export_status_port import ExportStatus
from service.assistant.llm_port import LlmClient
from service.assistant.models import Answer
from service.command_models import Command, CommandResult
from service.control_service_impl import InMemoryControlService
from service.data_models import DataPoint
from service.data_service import DataCallback
from service.data_service_impl import InMemoryDataService
from service.history import HistoryPoint, HistoryStore, NullHistoryStore
from service.sensor_data_processor import (
    SensorDataProcessor,
    StatisticsCallback,
    StatusCallback,
)
from service.ventilation_controller import (
    FanDecisionCallback,
    FanMode,
    VentilationController,
    VentilationSettings,
)


@dataclass(frozen=True)
class DeviceStatusView:
    """API-facing, decoupled snapshot of a device's status.

    Deliberately does not reuse device.state.DeviceStatus's enum types --
    it exposes plain bool/str fields instead -- so that callers above
    ApplicationRuntime (notably api/, which must not import device/ at
    all) can consume device status without depending on the device
    package.
    """

    device_id: DeviceId
    is_connected: bool
    is_occupied: bool
    occupant: ClientId | None
    channels: tuple[ChannelId, ...] = ()
    """Channel ids this device declares in its capability.

    Added 2026-09-08. A presentation端 needs it to offer only the channels
    the selected device actually has: in Simulator mode each simulator is
    its own device carrying **one** channel, so a fixed three-item channel
    list meant two of every three choices silently subscribed to nothing --
    the subscription succeeded, the activity log said "已订阅", and no data
    ever arrived. Hardware mode hid the problem because there one device
    carries all three channels, so every choice happened to be valid.

    Purely additive, with a default, so existing constructions and the
    ApiInterface guard test are unaffected."""


class ApplicationRuntime:
    """Owns one DeviceManager, DataService, and ControlService, wired together."""

    def __init__(self) -> None:
        self.devices = DeviceManager()
        self.data_service = InMemoryDataService()
        self.control_service = InMemoryControlService(transport=self.devices)
        # Independent of the device registry above: evaluates every
        # published DataPoint against known threshold rules
        # (temperature/humidity/noise), for whichever devices/channels
        # register_device() below auto-subscribes it to. Not required for
        # the core data/control loop -- see subscribe_alarm_status()'s
        # docstring for why this exists at the runtime level rather than
        # staying the standalone component it started as.
        self._alarm_processor = SensorDataProcessor()
        # Second per-channel processor, independent of the alarm one above:
        # it decides whether the ventilation fan should run, from its own
        # runtime-adjustable thresholds. See its module docstring for why
        # ventilation thresholds are deliberately separate from the alarm
        # thresholds rather than more rules inside SensorDataProcessor.
        self._ventilation = VentilationController()
        # Set by enable_fan_control(); until then ventilation decisions are
        # computed and published but never turned into device commands.
        self._fan_dispatcher: FanCommandDispatcher | None = None
        # Decides when a threshold alarm should be spoken aloud: requires
        # consecutive confirmation, then stays quiet for a cooldown. Fed
        # from the alarm processor's status stream, so it sees exactly the
        # same evaluations the UI does.
        self._announcer = AlarmAnnouncer()
        self._alarm_processor.on_status(self._announcer.handle_threshold_status)
        self._alert_dispatcher: AlertCommandDispatcher | None = None
        self._alarm_state_dispatcher: AlarmStateDispatcher | None = None
        self._answer_dispatcher: AnswerDispatcher | None = None
        # 历史记录默认不存：没挂存储时查询返回空、不抛异常，与助手没有模型时
        # 照常作答是同一条原则。真正的存储由组合根经 attach_history() 挂上——
        # 只有它知道数据库该落在哪个文件，这一层不碰路径与连接。
        self._history_store: HistoryStore = NullHistoryStore()
        self._history_recorder = HistoryRecorder(self._history_store)
        # Always present, so ``ask()`` works from the moment the runtime
        # exists. Without a model attached it answers from rules and
        # templates -- which is the default and always correct; see
        # docs/02_Architecture/Assistant_Design.md.
        self._llm: LlmClient | None = None
        self._export_status: ExportStatus | None = None
        """两个可选注入项，记在这里而不是只传给 Assistant。

        2026-09-18：在此之前 ``attach_language_model`` 直接重建 Assistant
        而不记住 llm，于是第二个注入项一出现，两次 attach 就会互相把对方
        的注入冲掉——谁后调用谁生效。现在统一走 :meth:`_rebuild_assistant`，
        调用顺序不再影响结果。"""
        self._assistant = self._build_assistant()

    def register_device(
        self,
        device: DeviceInterface,
        channel: CommunicationChannel,
        accepted_commands: Sequence[CommandType] = (),
    ) -> None:
        """Register a device (Simulator- or Hardware-mode) so it can receive
        commands, and -- for Simulator-mode devices -- report data.

        ``device`` may be a device.simulator.SimulatorDevice or a
        device.remote.RemoteDevice; both structurally satisfy
        DeviceInterface and register identically. Only devices that
        implement ``generate()`` (SimulatorDevice) support
        :meth:`report_data`, per DeviceManager.report_data()'s docstring.

        Also auto-subscribes the runtime's alarm processor to every
        channel ``device.capability`` declares, via
        :meth:`watch_alarms_for` -- see its docstring for why Hardware
        mode (``scripts/run_gui.py``'s ``build_hardware_runtime()``)
        cannot rely on this method doing that and must call
        ``watch_alarms_for`` itself instead.
        """
        self.devices.register(device, channel, accepted_commands)
        self.watch_device_channels(device)

    def watch_device_channels(self, device: DeviceInterface) -> None:
        """Auto-subscribe the runtime's per-channel processors -- threshold
        alarms *and* ventilation -- to every channel ``device.capability``
        declares, so both are evaluated for this device without the caller
        having to do anything extra. Symmetric with how ``subscribe()``/UI
        subscriptions are opt-in per channel, while alarm and ventilation
        evaluation are not (a channel can be in alarm, or hot enough to
        need ventilation, long before anyone views it).

        Both processors are subscribed to *every* declared channel and
        filter internally, rather than being wired only to the channels
        they care about: that keeps this method independent of which
        channel names each processor happens to act on.

        Called automatically by :meth:`register_device`. Exposed
        separately because Hardware mode's composition
        (``scripts/run_gui.py``'s ``build_hardware_runtime()``)
        deliberately calls ``self.devices.register(...)`` directly rather
        than through this facade's ``register_device()`` (so it can read
        back the assigned wire id from the returned DeviceRegistration --
        see that function's own docstring), which means it never runs
        through here on its own; it must call this method itself, right
        after registering.
        """
        for descriptor in device.capability.channels:
            self._alarm_processor.subscribe_to(
                self.data_service, device.device_id, descriptor.channel_id
            )
            self._ventilation.subscribe_to(
                self.data_service, device.device_id, descriptor.channel_id
            )
            self._history_recorder.subscribe_to(
                self.data_service, device.device_id, descriptor.channel_id
            )

    def watch_alarms_for(self, device: DeviceInterface) -> None:
        """Backwards-compatible alias for :meth:`watch_device_channels`.

        Kept because existing composition scripts call it by this name.
        It now also wires ventilation, which is why the general name
        exists -- prefer :meth:`watch_device_channels` in new code.
        """
        self.watch_device_channels(device)

    # -- device queries ---------------------------------------------------

    def list_devices(self) -> list[DeviceId]:
        """Return the ids of all currently registered devices."""
        return self.devices.list_device_ids()

    def get_device_status(self, device_id: DeviceId) -> DeviceStatusView:
        """Return a decoupled status snapshot for ``device_id``.

        Connection state comes from the Device model (device/); occupancy
        comes from InMemoryControlService, which is the authoritative
        owner-tracker for phase 1 -- SimulatorDevice/DeviceStatus's own
        occupy()/release() methods are not driven by the control path (see
        service/control_service_impl.py's get_owner() docstring).
        """
        registration = self.devices.get(device_id)
        connection_state = registration.device.status.connection_state
        owner = self.control_service.get_owner(device_id)
        return DeviceStatusView(
            device_id=device_id,
            is_connected=connection_state is ConnectionState.CONNECTED,
            is_occupied=owner is not None,
            occupant=owner,
            channels=tuple(
                descriptor.channel_id
                for descriptor in registration.device.capability.channels
            ),
        )

    # -- data path ----------------------------------------------------

    def subscribe(
        self, device_id: DeviceId, channel_id: ChannelId, callback: DataCallback
    ) -> str:
        """Subscribe ``callback`` to future data on device_id/channel_id."""
        return self.data_service.subscribe(device_id, channel_id, callback)

    def unsubscribe(self, subscription_id: str) -> None:
        self.data_service.unsubscribe(subscription_id)

    def subscribe_alarm_status(self, callback: StatusCallback) -> None:
        """Register ``callback`` for every future ThresholdStatus, across
        all registered devices/channels -- global, not per-device/channel
        like :meth:`subscribe`, since a caller (typically a UI) wants to
        know about alarms platform-wide, not just on channels it happens
        to already be displaying. No matching unsubscribe: nothing in
        this codebase currently needs to stop listening mid-session
        (compare to the per-subscription unsubscribe() above, which
        exists because UI channel subscriptions are dynamically toggled
        by the user)."""
        self._alarm_processor.on_status(callback)

    def subscribe_statistics(self, callback: StatisticsCallback) -> None:
        """Register ``callback`` for every future ChannelStatistics
        snapshot, across all registered devices/channels -- global, same
        reasoning as :meth:`subscribe_alarm_status`. Unlike alarm status,
        this fires for *any* numeric channel a registered device
        declares, not only temperature/humidity/noise -- see
        SensorDataProcessor.on_statistics's docstring."""
        self._alarm_processor.on_statistics(callback)

    # -- ventilation / fan control --------------------------------------

    def enable_alert_announcements(
        self, device_id: DeviceId, **dispatcher_options: str
    ) -> AlertCommandDispatcher:
        """Start turning confirmed threshold alarms into spoken-phrase
        commands on ``device_id``.

        Opt-in for the same reason as :meth:`enable_fan_control`: only the
        composition root knows which registered device has a speaker.
        Until this is called the runtime still evaluates alarms and
        applies the confirmation/cooldown rules, it just never commands
        anything. Calling it again replaces the previous dispatcher.

        Like the fan dispatcher, the returned object's
        ``dispatch_pending()`` must be driven from the caller's poll loop
        -- never from a data callback; see
        application/alert_dispatcher.py's module docstring.
        """
        dispatcher = AlertCommandDispatcher(
            self.control_service, device_id, **dispatcher_options
        )
        self._alert_dispatcher = dispatcher
        self._announcer.on_announcement(dispatcher.handle_announcement)
        return dispatcher

    @property
    def alert_dispatcher(self) -> AlertCommandDispatcher | None:
        """The dispatcher installed by :meth:`enable_alert_announcements`."""
        return self._alert_dispatcher

    def subscribe_announcement(self, callback: AnnouncementCallback) -> None:
        """Register ``callback`` for every future announcement decision.

        Exposed for observers that want to know a phrase was spoken (an
        activity log, a test) without being the thing that speaks it.
        """
        self._announcer.on_announcement(callback)

    # -- environment assistant -------------------------------------------

    @property
    def assistant(self) -> Assistant:
        """The Q&A assistant. Always available, model or no model."""
        return self._assistant

    def ask(self, question: str) -> Answer:
        """Answer one natural-language question. Never raises.

        Numbers come from this runtime's own processor and ventilation
        controller; see the assistant's module docstring for why a model
        is never allowed to supply one.
        """
        answer = self._assistant.ask(question)
        if self._answer_dispatcher is not None:
            # Recorded, not sent -- see the dispatcher's record() docstring.
            # Tagged as local here; the gateway's observer re-records a
            # phone question with the remote tag a moment later, which is
            # how "who asked" reaches the board without ApiInterface
            # having to carry it.
            self._answer_dispatcher.record(answer, remote=False)
        return answer

    def poll_assistant(self) -> Answer | None:
        """Collect a finished model rephrasing, if one is ready. Never raises.

        Call from the same poll loop that drives ``runner.run_once()``.
        Returns None in the overwhelmingly common case -- no model
        attached, nothing pending, or generation still running -- so it is
        cheap to call every cycle.
        """
        improved = self._assistant.poll_rephrasing()
        if improved is not None and self._answer_dispatcher is not None:
            # remote defaults to "same end as the question", which is what
            # a late rephrasing of it belongs to.
            self._answer_dispatcher.record(improved)
        return improved

    def attach_language_model(self, llm: LlmClient) -> None:
        """Replace the assistant's model client.

        Opt-in like :meth:`enable_fan_control`: only the composition root
        knows whether a local model service is reachable, and the feature
        is deliberately usable without one. Replaces the whole assistant
        rather than mutating it, so a half-finished rephrasing cannot
        survive the swap.
        """
        self._llm = llm
        self._rebuild_assistant()

    def attach_export_status(self, status: ExportStatus) -> None:
        """Let the assistant see how many archived hours await upload.

        Opt-in for the same reason as :meth:`attach_language_model`: only
        the composition root knows where the export ledger lives. Without
        it the assistant still recognises "把数据传上去" -- it just answers
        that it cannot tell how many are pending, which is true.

        Read-only by construction: the port exposes a count and nothing
        else, so attaching it cannot give the assistant a way to upload
        anything. Starting an upload stays with the button in the desktop
        UI (History_And_Cloud_Design.md §6.1).
        """
        self._export_status = status
        self._rebuild_assistant()

    def _build_assistant(self) -> Assistant:
        return Assistant(
            self._alarm_processor,
            self.list_devices,
            ventilation=self._ventilation,
            llm=self._llm,
            exports=self._export_status,
        )

    def _rebuild_assistant(self) -> None:
        """Replace the assistant, carrying every injection across.

        Replaced rather than mutated so a half-finished rephrasing cannot
        survive the swap -- the reason the language-model path did this
        from the start.
        """
        self._assistant = self._build_assistant()

    def attach_history(self, store: HistoryStore) -> None:
        """Start persisting readings to ``store``.

        Opt-in like :meth:`attach_language_model`, and for the same
        reason: only the composition root knows where the database
        belongs, and the system is deliberately usable without one. Until
        this is called, readings are recorded into a
        :class:`~service.history.NullHistoryStore` -- collected and
        discarded -- so every subscription is already in place and nothing
        needs re-wiring when a real store arrives.

        The recorder is replaced rather than re-pointed, so readings
        queued against the previous store cannot be written into the new
        one. Anything still pending there is dropped, which is correct:
        those readings belong to the store that was attached when they
        arrived.
        """
        self._history_store = store
        self._history_recorder = HistoryRecorder(store)
        for device_id in self.list_devices():
            device = self.devices.get(device_id).device
            for descriptor in device.capability.channels:
                self._history_recorder.subscribe_to(
                    self.data_service, device_id, descriptor.channel_id
                )

    @property
    def history_recorder(self) -> HistoryRecorder:
        """The recorder driving persistence.

        Exposed so the poll loop can call ``flush_if_due()`` and a
        composition script can read its counters, mirroring how
        :attr:`fan_dispatcher` exposes its own.
        """
        return self._history_recorder

    def query_history(
        self,
        device_id: DeviceId,
        channel_id: ChannelId,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[HistoryPoint]:
        """Read stored readings back, newest first.

        Returns an empty list when no store is attached rather than
        raising: "there is no history yet" is an ordinary state a caller
        displays, not an error it recovers from.
        """
        return self._history_store.query(device_id, channel_id, start, end, limit)

    def enable_alarm_state_mirroring(
        self, device_id: DeviceId, **dispatcher_options: str
    ) -> AlarmStateDispatcher:
        """Start mirroring per-channel alarm state onto ``device_id``.

        Opt-in for the same reason as :meth:`enable_fan_control` and
        :meth:`enable_alert_announcements`: only the composition root
        knows which registered device has a screen to display the state
        on. Calling it again replaces the previous dispatcher.

        The returned object's ``dispatch_pending()`` must be driven from
        the caller's poll loop, never from a data callback; see
        application/alarm_state_dispatcher.py's module docstring.
        """
        dispatcher = AlarmStateDispatcher(
            self.control_service, device_id, **dispatcher_options
        )
        self._alarm_state_dispatcher = dispatcher
        self._alarm_processor.on_status(dispatcher.handle_threshold_status)
        return dispatcher

    @property
    def alarm_state_dispatcher(self) -> AlarmStateDispatcher | None:
        """The dispatcher installed by :meth:`enable_alarm_state_mirroring`."""
        return self._alarm_state_dispatcher

    def enable_answer_display(
        self, device_id: DeviceId, **dispatcher_options: str
    ) -> AnswerDispatcher:
        """Start showing the last answer on ``device_id``'s second page.

        Opt-in like the other three, and for the same reason: only the
        composition root knows which registered device has a screen.

        Every answer produced through :meth:`ask` is recorded from here,
        so a consumer that never learned about this feature still feeds
        it -- the desktop panel and the phone gateway both go through
        ``ask``. The returned object's ``dispatch_pending()`` must be
        driven from the poll loop, never from a data callback.
        """
        dispatcher = AnswerDispatcher(
            self.control_service, device_id, **dispatcher_options
        )
        self._answer_dispatcher = dispatcher
        return dispatcher

    @property
    def answer_dispatcher(self) -> AnswerDispatcher | None:
        """The dispatcher installed by :meth:`enable_answer_display`."""
        return self._answer_dispatcher

    def enable_fan_control(
        self, device_id: DeviceId, **dispatcher_options: str
    ) -> FanCommandDispatcher:
        """Start turning ventilation decisions into commands on ``device_id``.

        Opt-in rather than automatic, because only the composition root
        knows which registered device actually carries a fan -- in
        Simulator mode there are three devices and none of them has one,
        in Hardware mode there is one that does. Until this is called the
        runtime still evaluates ventilation and publishes decisions (so a
        UI can display them), it just never commands anything.

        ``dispatcher_options`` is forwarded to
        :class:`~application.fan_dispatcher.FanCommandDispatcher`
        (``client_id``/``on_command``/``off_command``); the defaults suit
        the firmware's own command names. Calling this again replaces the
        previous dispatcher.
        """
        dispatcher = FanCommandDispatcher(
            self.control_service, device_id, **dispatcher_options
        )
        self._fan_dispatcher = dispatcher
        self._ventilation.on_decision(dispatcher.handle_decision)
        return dispatcher

    @property
    def fan_dispatcher(self) -> FanCommandDispatcher | None:
        """The dispatcher installed by :meth:`enable_fan_control`, if any.

        Exposed so a composition script or test can read its
        ``applied_state``/``failure_count`` counters without holding on to
        the object returned at wiring time.
        """
        return self._fan_dispatcher

    def subscribe_fan_decision(self, callback: FanDecisionCallback) -> None:
        """Register ``callback`` for every future ventilation decision.

        Global rather than per-device, same reasoning as
        :meth:`subscribe_alarm_status`: there is one fan, and a caller
        wants to know what it should be doing, not which channel asked.
        Fires on every evaluated reading and on every settings change --
        see VentilationController's module docstring.
        """
        self._ventilation.on_decision(callback)

    def get_ventilation_settings(self) -> VentilationSettings:
        """Return the current ventilation thresholds and fan mode."""
        return self._ventilation.settings

    def set_ventilation_thresholds(
        self, temperature_max: float | None = None, humidity_max: float | None = None
    ) -> None:
        """Adjust either or both ventilation thresholds at runtime.

        ``None`` leaves that threshold unchanged. Does **not** touch the
        threshold-alarm rules in service.sensor_data_processor, which stay
        fixed on purpose.
        """
        self._ventilation.set_thresholds(temperature_max, humidity_max)

    def set_fan_mode(self, mode: FanMode) -> None:
        """Switch the fan between automatic control and a manual override."""
        self._ventilation.set_mode(mode)

    # -- data path (continued) ------------------------------------------

    def report_data(self, device_id: DeviceId, channel_id: ChannelId) -> DataPoint:
        """Run one full uplink cycle and publish the result to subscribers."""
        point = self.devices.report_data(device_id, channel_id)
        self.data_service.publish(point)
        return point

    # -- control path ---------------------------------------------------

    def acquire(self, device_id: DeviceId, client_id: ClientId) -> bool:
        return self.control_service.acquire(device_id, client_id)

    def release(self, device_id: DeviceId, client_id: ClientId) -> None:
        self.control_service.release(device_id, client_id)

    def submit_command(self, command: Command) -> CommandResult:
        """Run one full downlink cycle and return the device's final result."""
        return self.control_service.submit_command(command)

    def get_result(self, command_id: str) -> CommandResult:
        return self.control_service.get_result(command_id)
