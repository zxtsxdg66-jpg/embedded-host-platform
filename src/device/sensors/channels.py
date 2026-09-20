"""Shared channel-id constants for the environmental sensor simulators.

Centralized here so device/sensors/*.py (which define these channels on
their SimulatorDevice presets) and service/sensor_data_processor.py (which
evaluates alarm thresholds per channel) never drift apart on the literal
channel-name string.
"""

from __future__ import annotations

from core.models import ChannelId

TEMPERATURE_CHANNEL: ChannelId = "temperature"
HUMIDITY_CHANNEL: ChannelId = "humidity"
NOISE_CHANNEL: ChannelId = "noise"
