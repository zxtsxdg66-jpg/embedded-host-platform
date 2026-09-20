"""Service: core service layer (device lifecycle, data model, command
model, multi-client access rules).

Currently implemented: the data/command models and the two base service
interfaces (DataService, ControlService). Concrete implementations
(device lifecycle management, in-memory or gateway-backed dispatch) are
added in a later phase. See src/service/README.md for the full module scope.
"""

from service.command_models import Command, CommandResult, CommandStatus
from service.control_service import ControlService
from service.data_models import DataPoint
from service.data_service import DataCallback, DataService

__all__ = [
    "Command",
    "CommandResult",
    "CommandStatus",
    "ControlService",
    "DataPoint",
    "DataCallback",
    "DataService",
]
