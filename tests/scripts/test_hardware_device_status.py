"""硬件模式下设备连接状态的回归测试。

**这个不变量为什么值得单独测：**

`SimulatorDevice` 在自己的构造里就把状态标成了 CONNECTED（见 `device/simulator.py`），
而 `RemoteDevice` 用的是 `DeviceStatus` 的默认值 DISCONNECTED。
两个硬件组装函数此前都没有显式设置它，导致真实硬件模式下界面顶部一直显示"未连接"，
而数据其实在正常刷新——同一件事，两种模式给出了互相矛盾的呈现。
该问题是在为论文截取界面图时才被发现的（截图上"未连接"与实时数据同框出现）。

更重要的是，这属于本项目已经踩过一次的同一类问题：
**`scripts/run_gui.py` 与 `scripts/run_api_server.py` 是两条独立的装配路径**，
任何"设备注册时要做的事"都必须两处都做（上一次是报警订阅漏调用）。
因此这里对两条路径同时断言，而不是只测其中一条。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.local_api import LocalApi

_FAKE_PORT = "COM_TEST"


@pytest.fixture
def fake_serial():
    """把 pyserial 的端口枚举与串口对象都换成假的，使组装过程不需要真实硬件。"""
    ports = [SimpleNamespace(device=_FAKE_PORT)]
    with (
        patch("communication.serial.list_ports.comports", return_value=ports),
        patch("serial.Serial"),
    ):
        yield


def test_gui_hardware_mode_reports_device_connected(fake_serial) -> None:
    from scripts.run_gui import build_hardware_runtime

    runtime, _runner = build_hardware_runtime(port=_FAKE_PORT)
    api = LocalApi(runtime)

    devices = api.list_devices()
    assert devices, "硬件模式应注册一台设备"
    for device_id in devices:
        assert api.get_device_status(device_id).is_connected, (
            "串口已打开成功，设备却报告未连接——界面会出现「未连接但有数据」的矛盾"
        )


def test_gateway_hardware_mode_reports_device_connected(fake_serial) -> None:
    """网关侧是另一条独立的装配路径，必须同样成立。"""
    from scripts.run_api_server import build_hardware_runtime

    runtime, _targets, _runner = build_hardware_runtime(serial_port=_FAKE_PORT)
    api = LocalApi(runtime)

    devices = api.list_devices()
    assert devices
    for device_id in devices:
        assert api.get_device_status(device_id).is_connected


def test_both_modes_agree_on_connection_state(fake_serial) -> None:
    """模拟模式与硬件模式对"设备是否已连接"应给出一致的呈现。

    二者的底层实现不同（SimulatorDevice 自带状态，RemoteDevice 由组装方设置），
    但对界面而言应当没有区别——这正是「通信介质无关」的一部分。
    """
    from scripts.run_gui import build_hardware_runtime, build_simulator_runtime

    sim_runtime, _ = build_simulator_runtime()
    hw_runtime, _ = build_hardware_runtime(port=_FAKE_PORT)

    sim_api, hw_api = LocalApi(sim_runtime), LocalApi(hw_runtime)
    sim_states = {
        sim_api.get_device_status(d).is_connected for d in sim_api.list_devices()
    }
    hw_states = {
        hw_api.get_device_status(d).is_connected for d in hw_api.list_devices()
    }

    assert sim_states == {True}
    assert hw_states == {True}
