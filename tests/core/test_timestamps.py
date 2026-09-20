from datetime import datetime, timedelta, timezone

import pytest

from core.timestamps import from_iso8601, monotonic_ms, now_utc, to_iso8601


def test_now_utc_is_timezone_aware() -> None:
    moment = now_utc()
    assert moment.tzinfo is not None
    assert moment.tzinfo.utcoffset(moment) == timedelta(0)


def test_to_iso8601_roundtrip() -> None:
    moment = now_utc()
    text = to_iso8601(moment)
    restored = from_iso8601(text)
    assert restored == moment


def test_to_iso8601_rejects_naive_datetime() -> None:
    naive = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(ValueError):
        to_iso8601(naive)


def test_from_iso8601_rejects_naive_text() -> None:
    with pytest.raises(ValueError):
        from_iso8601("2026-01-01T12:00:00")


def test_from_iso8601_normalizes_to_utc() -> None:
    restored = from_iso8601("2026-01-01T12:00:00+08:00")
    assert restored.tzinfo == timezone.utc
    assert restored.hour == 4


def test_monotonic_ms_is_non_decreasing() -> None:
    first = monotonic_ms()
    second = monotonic_ms()
    assert second >= first
