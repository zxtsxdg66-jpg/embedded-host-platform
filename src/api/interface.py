"""API abstract interface: the unified entry point future clients call through.

Corresponds to docs/02_Architecture/Multi_Client_System_Architecture.md
Section 5 ("PC 端和 Android 端调用关系"): PC and Android Presentation
layers are meant to face "同一套概念接口" regardless of whether the
implementation behind it is local (direct mode, phase 1) or remote
(gateway mode, a later phase) -- this ABC is that concept interface.
Corresponds also to docs/02_Architecture/Core_Service_Design.md Section 8
item 1 ("本地调用接口的正式化定义").

API Layer boundary (see module docstrings in api/local_api.py and
api/exceptions.py for the rationale): this module imports only from
`core`, `service`, and `application` -- never `device`, `communication`,
or `protocol`. It is a facade over ApplicationRuntime, not a new place to
implement device/communication/protocol logic.

Capabilities, per the task this module was built for:

1. list_devices        -- 查询设备列表
2. get_device_status    -- 查询设备状态
3. subscribe_data / unsubscribe_data -- 数据订阅
4. acquire_control / release_control / submit_command -- 提交控制命令
   (acquire_control/release_control are the occupancy mechanics that make
   submit_command usable under Core_Service_Design.md Section 7's default
   "共享读、独占写" rule -- they are not a separate capability, they are
   part of what "submitting a control command" requires)
5. get_command_result   -- 查询命令结果
6. subscribe_alarm_status -- 阈值报警状态订阅（2026-08-12 新增，见
   docs/05_Test/Hardware_Simulation_Mode.md"阈值报警"一节；
   service.sensor_data_processor.SensorDataProcessor 已实现的能力此前
   未接入 api/ui，这是那次补充）
7. subscribe_statistics -- 统计信息订阅（2026-08-12 新增，同一次补充里
   一并接入的 SensorDataProcessor.get_statistics() 能力，供 ui 的
   StatisticsPanelWidget 使用）
8. get_ventilation_settings / set_ventilation_thresholds / set_fan_mode /
   subscribe_fan_decision -- 通风控制（2026-09-07 新增，经用户授权扩展）
9. ask -- 环境问答（2026-09-08 新增，经用户授权扩展）。呈现端只能 import
   `api`，聊天面板因此必须经由本接口访问助手；助手本身在
   service.assistant，设计见 docs/02_Architecture/Assistant_Design.md
10. query_history -- 历史读数查询（2026-09-17 新增，经用户授权扩展）。
    与 8/9 两项一样属于纯增量：既有方法签名一个未动。设计见
    docs/02_Architecture/History_And_Cloud_Design.md
11. get_link_statistics / subscribe_link_events -- 串口链路监视（2026-09-23
    新增，经用户授权扩展）。供 Web 控制台的协议检查器使用；纯增量，
    既有方法签名一个未动。设计见 docs/02_Architecture/Web_Console_Design.md
    第 5 节
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from application.link_monitor import LinkEventCallback, LinkStatistics
from application.runtime import DeviceStatusView
from core.models import ChannelId, ClientId, DeviceId
from service.assistant.models import Answer
from service.command_models import Command, CommandResult
from service.data_service import DataCallback
from service.history import HistoryPoint
from service.sensor_data_processor import StatisticsCallback, StatusCallback
from service.ventilation_controller import (
    FanDecisionCallback,
    FanMode,
    VentilationSettings,
)


class ApiInterface(ABC):
    """Unified entry point for future PC (PyQt6) and Android clients."""

    @abstractmethod
    def list_devices(self) -> list[DeviceId]:
        """Return the ids of all currently registered devices."""

    @abstractmethod
    def get_device_status(self, device_id: DeviceId) -> DeviceStatusView:
        """Return a status snapshot for ``device_id``."""

    @abstractmethod
    def subscribe_data(
        self, device_id: DeviceId, channel_id: ChannelId, callback: DataCallback
    ) -> str:
        """Subscribe ``callback`` to future data on device_id/channel_id.

        Returns an opaque subscription id usable with :meth:`unsubscribe_data`.
        """

    @abstractmethod
    def unsubscribe_data(self, subscription_id: str) -> None:
        """Remove a previously registered data subscription, if it still exists."""

    @abstractmethod
    def acquire_control(self, device_id: DeviceId, client_id: ClientId) -> bool:
        """Attempt to acquire exclusive command authority over ``device_id``."""

    @abstractmethod
    def release_control(self, device_id: DeviceId, client_id: ClientId) -> None:
        """Release command authority previously acquired by ``client_id``."""

    @abstractmethod
    def submit_command(self, command: Command) -> CommandResult:
        """Submit ``command`` for dispatch, returning its final result."""

    @abstractmethod
    def get_command_result(self, command_id: str) -> CommandResult:
        """Retrieve the result of a previously submitted command."""

    @abstractmethod
    def subscribe_alarm_status(self, callback: StatusCallback) -> None:
        """Register ``callback`` for every future threshold-status event,
        across all devices/channels that have a threshold rule
        (temperature/humidity/noise, per
        service.sensor_data_processor). Global, not per-device/channel:
        unlike :meth:`subscribe_data`, a caller wants to know about
        alarms platform-wide, not only on channels it happens to already
        be displaying. Fires for every evaluated point, not only
        violations -- ``ThresholdStatus.triggered`` distinguishes the
        two, so a caller can also detect when a channel returns to
        normal, not just when it goes into alarm.
        """

    @abstractmethod
    def subscribe_statistics(self, callback: StatisticsCallback) -> None:
        """Register ``callback`` for every future ChannelStatistics
        snapshot (current/minimum/maximum/average/sample_count), across
        all devices/channels. Global, same reasoning as
        :meth:`subscribe_alarm_status`. Unlike that method, this fires
        for *any* numeric channel, not only ones with a threshold rule.
        """

    # -- ventilation / fan control (2026-09-07) --------------------------
    #
    # Added for the ventilation feature: the fan must react to temperature
    # and humidity automatically, be overridable by hand, and -- unlike the
    # threshold alarms -- have thresholds that are adjustable while running
    # (see service/ventilation_controller.py for why the two threshold sets
    # are deliberately separate). Extending this protected interface was
    # authorised explicitly; the additions are purely additive, no existing
    # method's signature changed.

    @abstractmethod
    def get_ventilation_settings(self) -> VentilationSettings:
        """Return the current ventilation thresholds and fan mode."""

    @abstractmethod
    def set_ventilation_thresholds(
        self, temperature_max: float | None = None, humidity_max: float | None = None
    ) -> None:
        """Adjust either or both ventilation thresholds at runtime.

        ``None`` leaves that threshold unchanged, so a caller can move one
        without knowing the other. These are **not** the threshold-alarm
        limits, which stay fixed -- see
        :meth:`subscribe_alarm_status`.
        """

    @abstractmethod
    def set_fan_mode(self, mode: FanMode) -> None:
        """Switch the fan between automatic control and a manual override."""

    @abstractmethod
    def subscribe_fan_decision(self, callback: FanDecisionCallback) -> None:
        """Register ``callback`` for every future ventilation decision.

        Global, not per-device: there is one fan, and a caller wants to
        know what it should be doing. Like
        :meth:`subscribe_alarm_status`, this fires for every evaluated
        reading (not only when the desired state changes) so a view can
        render the current state and its reason continuously; it also
        fires immediately whenever thresholds or mode change.
        """

    @abstractmethod
    def ask(self, question: str) -> Answer:
        """Answer a natural-language question about the monitored environment.

        Returns immediately with a complete answer composed from the
        platform's own data: intent recognition and templating are pure
        code, so there is nothing to wait for. **Every number in the
        answer is read from the data layer**; a language model, when one
        is attached, only rephrases the sentence around those numbers and
        its output is discarded if it contains a figure the data did not
        supply. See docs/02_Architecture/Assistant_Design.md section 1.1.

        Never raises for an unrecognised question -- the returned
        :class:`~service.assistant.models.Answer` carries
        ``AnswerSource.FALLBACK`` and text listing what can be asked.
        """

    @abstractmethod
    def query_history(
        self,
        device_id: DeviceId,
        channel_id: ChannelId,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[HistoryPoint]:
        """Return stored readings for one channel, newest first.

        ``limit`` defaults to 500 to match the desktop history table's own
        bound: a query should not be able to pull a day's readings into
        memory because a caller omitted an argument.

        Returns an empty list -- rather than raising -- when no store is
        attached or the range holds nothing. Both are ordinary states: a
        view displays "no data", it does not recover from an exception.
        """

    @abstractmethod
    def get_link_statistics(self) -> LinkStatistics:
        """Counters for the serial link: frames, resyncs, CRC failures.

        Added 2026-09-23 for the web console's protocol inspector (see
        docs/02_Architecture/Web_Console_Design.md section 5) -- the one
        extension of this interface that work required. ``active`` is False
        in Simulator mode, which has no byte stream to count.
        """

    @abstractmethod
    def subscribe_link_events(self, callback: LinkEventCallback) -> None:
        """Register ``callback`` for every frame and link anomaly.

        Called on the runtime's driver thread; the callback must not block.
        """

