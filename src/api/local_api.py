"""LocalApi: in-process ApiInterface implementation, a thin facade over
ApplicationRuntime.

Corresponds to docs/02_Architecture/Core_Service_Design.md Section 5.1
(direct-mode local calling): this is that local calling path, realized for
phase 1 as the concrete ApiInterface implementation. A later gateway-mode
implementation (Section 5.2/6.3) would implement the same ApiInterface
over a network transport instead of an in-process ApplicationRuntime
reference -- callers above this layer would not need to change.

API Layer boundary, enforced simply by this module's imports: no
`device`, `communication`, or `protocol` import anywhere in api/ --
every capability here is implemented purely in terms of what
`application.ApplicationRuntime` already exposes, plus translating its
generic core.exceptions.NotFoundError/StateTransitionError into the more
specific api.exceptions types a facade caller can branch on (see
api/exceptions.py for why).
"""

from __future__ import annotations

from datetime import datetime

from api.exceptions import (
    CommandAuthorityError,
    CommandDeliveryError,
    CommandNotFoundError,
    DeviceNotFoundError,
)
from api.interface import ApiInterface
from application.runtime import ApplicationRuntime, DeviceStatusView
from core.exceptions import NotFoundError, OperationTimeoutError, StateTransitionError
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


class LocalApi(ApiInterface):
    """In-process ApiInterface implementation delegating to one ApplicationRuntime."""

    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

    def list_devices(self) -> list[DeviceId]:
        return self._runtime.list_devices()

    def get_device_status(self, device_id: DeviceId) -> DeviceStatusView:
        try:
            return self._runtime.get_device_status(device_id)
        except NotFoundError as exc:
            raise DeviceNotFoundError(str(exc)) from exc

    def subscribe_data(
        self, device_id: DeviceId, channel_id: ChannelId, callback: DataCallback
    ) -> str:
        return self._runtime.subscribe(device_id, channel_id, callback)

    def unsubscribe_data(self, subscription_id: str) -> None:
        self._runtime.unsubscribe(subscription_id)

    def acquire_control(self, device_id: DeviceId, client_id: ClientId) -> bool:
        return self._runtime.acquire(device_id, client_id)

    def release_control(self, device_id: DeviceId, client_id: ClientId) -> None:
        self._runtime.release(device_id, client_id)

    def submit_command(self, command: Command) -> CommandResult:
        try:
            return self._runtime.submit_command(command)
        except NotFoundError as exc:
            raise DeviceNotFoundError(str(exc)) from exc
        except StateTransitionError as exc:
            raise CommandAuthorityError(str(exc)) from exc
        except OperationTimeoutError as exc:
            raise CommandDeliveryError(str(exc)) from exc

    def get_command_result(self, command_id: str) -> CommandResult:
        try:
            return self._runtime.get_result(command_id)
        except NotFoundError as exc:
            raise CommandNotFoundError(str(exc)) from exc

    def subscribe_alarm_status(self, callback: StatusCallback) -> None:
        self._runtime.subscribe_alarm_status(callback)

    def subscribe_statistics(self, callback: StatisticsCallback) -> None:
        self._runtime.subscribe_statistics(callback)

    def get_ventilation_settings(self) -> VentilationSettings:
        return self._runtime.get_ventilation_settings()

    def set_ventilation_thresholds(
        self, temperature_max: float | None = None, humidity_max: float | None = None
    ) -> None:
        self._runtime.set_ventilation_thresholds(temperature_max, humidity_max)

    def set_fan_mode(self, mode: FanMode) -> None:
        self._runtime.set_fan_mode(mode)

    def subscribe_fan_decision(self, callback: FanDecisionCallback) -> None:
        self._runtime.subscribe_fan_decision(callback)

    def ask(self, question: str) -> Answer:
        """Delegate to the runtime's assistant.

        Unlike the other methods here there is no exception translation to
        do: the assistant is documented never to raise, because "I did not
        understand" and "there is no data yet" are ordinary answers rather
        than error conditions -- a chat panel has nothing useful to do
        with an exception, but it can display either of those sentences.
        """
        return self._runtime.ask(question)

    def query_history(
        self,
        device_id: DeviceId,
        channel_id: ChannelId,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[HistoryPoint]:
        """Delegate to the runtime's history store.

        No exception translation here either: the stores are documented
        never to raise, and an unknown device simply has no readings --
        which is a legitimate answer, not a DeviceNotFoundError. That
        differs from ``get_device_status()`` deliberately: asking the
        status of a device that does not exist is a caller mistake, while
        asking for history that does not exist is how a view finds out
        there is none.
        """
        return self._runtime.query_history(device_id, channel_id, start, end, limit)
