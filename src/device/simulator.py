"""Device simulator (phase 1): produces flowing data without real hardware.

Corresponds to docs/architecture.md
(Device Simulator design). Phase 1 scope is deliberately narrow: build a
``SimulatorDevice`` that structurally satisfies ``DeviceInterface`` and can
generate ``DataPoint`` readings and publish them through a ``DataService``,
giving the platform its first end-to-end flowing-data path -- Device
abstraction -> Service Layer data distribution -- with no real MCU,
Protocol Layer, or Communication Layer involved yet.

Deferred to a later phase, once ``protocol`` and ``communication`` have real
implementations (per Section 6.2: "the simulator is a replaceable Hardware
Device Layer implementation, presented through a Communication Layer
interface"):
- protocol-frame-level command/response simulation
- connection-level fault injection (timeout, CRC failure, disconnect)
- being driven through the Communication Layer's abstract interface rather
  than called directly

Phase 1 simplification: a ``SimulatorDevice`` reports itself as always
``CONNECTED`` on construction, since there is no real connection process
for it to go through yet; a later phase should let its connection state be
driven externally once Communication Layer semantics exist.

Not bound to any specific sensor, controlled object, or MCU model: channel
values come from generic, injectable value generators (constant / sequence
/ random) that carry no physical-quantity meaning -- that meaning, if any,
belongs to whoever configures a concrete simulated channel, never to this
module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from itertools import cycle
from random import Random
from typing import Any

from core.exceptions import NotFoundError
from core.models import ChannelId, DeviceId
from core.timestamps import now_utc
from device.capability import ChannelDescriptor, DeviceCapability
from device.metadata import DeviceMetadata
from device.model import Device
from device.state import ConnectionState, DeviceStatus
from service.data_models import DataPoint
from service.data_service import DataService


class ValueGenerator(ABC):
    """Generic, injectable source of channel values.

    Deliberately carries no physical-quantity semantics -- it produces
    values, not "temperature" or "voltage" readings.
    """

    @abstractmethod
    def next_value(self) -> Any:
        """Return the next value to report on a channel."""


@dataclass
class ConstantValueGenerator(ValueGenerator):
    """Always yields the same value."""

    value: Any

    def next_value(self) -> Any:
        return self.value


@dataclass
class SequenceValueGenerator(ValueGenerator):
    """Cycles endlessly through a fixed, non-empty sequence of values."""

    values: Sequence[Any]
    _iterator: Iterator[Any] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("values must not be empty")
        self._iterator = cycle(self.values)

    def next_value(self) -> Any:
        return next(self._iterator)


@dataclass
class RandomValueGenerator(ValueGenerator):
    """Yields uniformly distributed floats in ``[low, high)``.

    Draws from a locally injected ``random.Random`` instance rather than
    the global ``random`` module, so a caller can pass a seeded instance
    for deterministic, reproducible test runs without touching global RNG
    state (see the Python code-quality guidelines guidance on
    injectable RNGs).
    """

    low: float
    high: float
    rng: Random = field(default_factory=Random)

    def next_value(self) -> float:
        return self.rng.uniform(self.low, self.high)


@dataclass(frozen=True)
class SimulatedChannel:
    """Binds one channel id to the generator that produces its values."""

    channel_id: ChannelId
    generator: ValueGenerator
    description: str = ""


class SimulatorDevice:
    """A device backed by generated data instead of real hardware.

    Structurally satisfies ``device.interface.DeviceInterface``
    (``device_id`` / ``capability`` / ``status``), so the Service Layer can
    treat it exactly like a device reached through a real communication
    channel, per docs/architecture.md.
    """

    def __init__(
        self,
        device_id: DeviceId,
        channels: Sequence[SimulatedChannel],
        name: str = "",
    ) -> None:
        if not channels:
            raise ValueError("a simulator device needs at least one channel")

        self._channels: dict[ChannelId, SimulatedChannel] = {
            channel.channel_id: channel for channel in channels
        }
        capability = DeviceCapability(
            channels=tuple(
                ChannelDescriptor(
                    channel_id=channel.channel_id, description=channel.description
                )
                for channel in channels
            )
        )
        # Phase 1 simplification: see module docstring.
        status = DeviceStatus(connection_state=ConnectionState.CONNECTED)
        self._device = Device(
            device_id=device_id,
            capability=capability,
            status=status,
            metadata=DeviceMetadata(name=name),
        )

    @property
    def device_id(self) -> DeviceId:
        return self._device.device_id

    @property
    def capability(self) -> DeviceCapability:
        return self._device.capability

    @property
    def status(self) -> DeviceStatus:
        return self._device.status

    @property
    def device(self) -> Device:
        """The underlying immutable Device snapshot."""
        return self._device

    def generate(self, channel_id: ChannelId) -> DataPoint:
        """Generate a single DataPoint for one configured channel."""
        try:
            channel = self._channels[channel_id]
        except KeyError as exc:
            raise NotFoundError(f"unknown channel: {channel_id!r}") from exc
        return DataPoint(
            device_id=self.device_id,
            channel=channel_id,
            value=channel.generator.next_value(),
            timestamp=now_utc(),
        )

    def generate_all(self) -> list[DataPoint]:
        """Generate one DataPoint per configured channel (one simulated "tick")."""
        return [self.generate(channel_id) for channel_id in self._channels]

    def publish_to(self, data_service: DataService, channel_id: ChannelId) -> DataPoint:
        """Generate one DataPoint for ``channel_id`` and publish it via
        ``data_service``.

        This is the platform's first end-to-end flowing-data path: a
        simulated device produces a DataPoint that travels through the
        Service Layer's DataService contract to any subscriber, with no
        real hardware, protocol, or communication layer involved yet.
        """
        point = self.generate(channel_id)
        data_service.publish(point)
        return point
