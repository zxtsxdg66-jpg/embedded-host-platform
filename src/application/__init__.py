"""Application: phase-1 runtime that wires Device/Protocol/Communication/Service
together into one hardware-free, runnable data and control loop.

See src/application/README.md for module scope.
"""

from application.manager import DeviceManager, DeviceRegistration
from application.runtime import ApplicationRuntime, DeviceStatusView

__all__ = [
    "ApplicationRuntime",
    "DeviceStatusView",
    "DeviceManager",
    "DeviceRegistration",
]
