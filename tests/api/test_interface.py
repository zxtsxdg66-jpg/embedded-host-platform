import pytest

from api.interface import ApiInterface


def test_api_interface_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        ApiInterface()  # type: ignore[abstract]


def test_api_interface_declares_expected_abstract_members() -> None:
    assert ApiInterface.__abstractmethods__ == frozenset(
        {
            "list_devices",
            "get_device_status",
            "subscribe_data",
            "unsubscribe_data",
            "acquire_control",
            "release_control",
            "submit_command",
            "get_command_result",
            "subscribe_alarm_status",
            "subscribe_statistics",
            # Ventilation / fan control, added 2026-09-07 with explicit
            # authorisation to extend this protected interface. Purely
            # additive -- no existing member changed.
            "get_ventilation_settings",
            "set_ventilation_thresholds",
            "set_fan_mode",
            "subscribe_fan_decision",
            # Environment Q&A, added 2026-09-08 with explicit authorisation.
            # Needed here rather than beside the assistant because src/ui/
            # may only import src/api/ -- the chat panel has no other way
            # to reach it. Also purely additive.
            "ask",
            # History queries, added 2026-09-17 with explicit authorisation.
            # Same reason it has to live here: the desktop history table and
            # the gateway's history endpoint are both presentation, and
            # presentation may only reach the platform through this facade.
            # Purely additive -- no existing member changed.
            "query_history",
        }
    )
