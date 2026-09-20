# device

## 职责

`device` 实现 `docs/02_Architecture/Core_Service_Design.md` 第 1 节定义的 **Device 抽象**，为系统提供与具体设备型号解耦的通用设备模型；`simulator.py` 实现第 6 节定义的**设备模拟器（第一阶段）**。

已实现：

- 设备标识（Device Identity）—— `core.models.DeviceId`
- 设备能力描述（Device Capability Descriptor）—— `capability.py`
- 连接状态（Connection State）/ 占用状态（Occupancy State）—— `state.py`
- 设备元信息（Device Metadata）—— `metadata.py`
- Device 抽象接口 / 具体模型 —— `interface.py` / `model.py`
- 设备模拟器（Simulator 模式：生成 Device 抽象与 DataPoint，并可通过 `DataService` 发布）—— `simulator.py`
- 外部真实设备的被动表示（Hardware 模式）—— `remote.py`：`RemoteDevice`，只维护 device_id/capability/status，不生成数据、不依赖 `communication`，详见 `docs/05_Test/Hardware_Simulation_Mode.md`
- 环境监测传感器模拟预设（`sensors/` 子包）—— `TemperatureSensorSimulator`/`HumiditySensorSimulator`/`NoiseSensorSimulator`，均为 `SimulatorDevice` 子类，用于在真实 STM32+传感器到位前验证数据处理链路，详见 `device/sensors/README.md`

两种模式的选用说明见 `docs/05_Test/Hardware_Simulation_Mode.md`；启动方式见 `docs/05_Test/Runtime_Mode.md`。

> 更新：从 `SerialChannel` 持续读取字节、解码为 `Frame`、映射回 `RemoteDevice` 的数据接收循环已在 `application/hardware_runtime.py`（`HardwareDeviceReceiver`）与 `application/hardware_runner.py`（`HardwareRuntimeRunner`，负责 `start`/`stop`/持续轮询驱动）中实现——**不在 `device` 模块内**，`RemoteDevice` 本身依旧不依赖 `communication`、不主动做任何 I/O，符合本模块的设计约束。

后续阶段（待真实 MCU 接入时再实现，不在当前范围）：

- `RemoteDevice` 的状态如何随真实连接（`SerialChannel`）建立/断开而自动更新（当前 `with_status()` 需由 `application` 层显式调用，`RemoteDevice` 自身不会感知连接事件）
- 模拟器的协议帧级应答、连接级异常注入（超时/CRC 失败/断线）

## 设计约束

- **不绑定具体传感器、控制对象或 MCU 型号**（STM32 / MSPM0 / ESP32 等仅作为元信息存在，不参与业务逻辑判断）
- 不感知具体通信介质（UART/USB/TCP/蓝牙等），设备的可达性由 `communication` 模块通过 `protocol` 模块间接提供
- 由 `service` 模块在建立连接、完成能力协商后构建与管理，`device` 模块本身只定义抽象与数据结构

## 依赖关系

依赖 `core`；被 `service` 依赖。

## 相关文档

- `docs/02_Architecture/Core_Service_Design.md`（第 1 节 Device 抽象设计）
- `docs/02_Architecture/System_Architecture.md`
