from device.interface import DeviceInterface
from device.model import Device


def test_device_structurally_satisfies_device_interface() -> None:
    device = Device(device_id="dev-1")
    assert hasattr(device, "device_id")
    assert hasattr(device, "capability")
    assert hasattr(device, "status")
    assert isinstance(device, DeviceInterface)
