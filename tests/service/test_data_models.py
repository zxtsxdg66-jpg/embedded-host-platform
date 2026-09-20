from datetime import timezone

from service.data_models import DataPoint


def test_data_point_defaults() -> None:
    point = DataPoint(device_id="dev-1", channel="ch1", value=42)
    assert point.device_id == "dev-1"
    assert point.channel == "ch1"
    assert point.value == 42
    assert point.valid is True
    assert point.timestamp.tzinfo == timezone.utc


def test_data_point_can_be_marked_invalid() -> None:
    point = DataPoint(device_id="dev-1", channel="ch1", value=None, valid=False)
    assert point.valid is False
