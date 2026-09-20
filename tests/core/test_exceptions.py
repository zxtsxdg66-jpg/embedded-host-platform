import pytest

from core.exceptions import (
    NotFoundError,
    OperationTimeoutError,
    PlatformError,
    StateTransitionError,
    ValidationError,
)


@pytest.mark.parametrize(
    "exc_type",
    [ValidationError, StateTransitionError, NotFoundError, OperationTimeoutError],
)
def test_all_exceptions_are_platform_errors(exc_type: type[Exception]) -> None:
    assert issubclass(exc_type, PlatformError)


def test_platform_error_is_exception() -> None:
    assert issubclass(PlatformError, Exception)


def test_exception_carries_message() -> None:
    with pytest.raises(ValidationError, match="bad input"):
        raise ValidationError("bad input")
