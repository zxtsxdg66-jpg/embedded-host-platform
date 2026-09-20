# Simulator 模式与 Hardware 模式

## 文档定位

本文档说明系统当前支持的两种运行模式——**Simulator 模式**（软件闭环验证）与 **Hardware 模式**（真实 MCU 接入）——各自的用途、链路组成，以及未来真实 MCU 只需实现的最小集合。

**本文档不讲怎么启动。** 用哪个启动器、加什么参数、COM 口怎么配，见
[`Runtime_Mode.md`](Runtime_Mode.md)。两份文档的分工是：那份回答"怎么跑"，
本份回答"为什么两种模式能共用同一套上层代码"。

本文档不修改、不替代 `docs/02_Architecture/` 下的任何架构文档；两种模式共享同一套五层架构（`System_Architecture.md`）与同一套 Device 抽象（`Core_Service_Design.md` 第 1 节），差异仅在于 Hardware Device Layer 与 Communication Layer 具体使用哪一个实现。

## 两种模式概览

```
Simulator 模式：
  SimulatorDevice  +  LoopbackChannel  +  Protocol

Hardware 模式：
  RemoteDevice     +  SerialChannel    +  Protocol
```

两条链路在 Protocol Layer 及以上（`protocol` → `application` → `service` → `api` → `ui`）**完全共用同一套代码**，不存在任何 if/else 分支区分"当前是哪种模式"——这正是 `CommunicationChannel`/`DeviceInterface` 两个抽象接口存在的意义（详见 `Core_Service_Design.md` 第 6.2 节："模拟器在接口层面与真实设备不可区分"）。

## Simulator 模式

### 用途

- **UI 开发**：在没有真实设备、甚至没有真实通信硬件的情况下，开发和调试 PyQt6 界面（设备列表、状态面板、实时曲线、控制面板）
- **数据链路验证**：验证从"设备产生数据"到"界面显示数据"的完整链路是否正确（编码/解码、发布/订阅、多通道、历史记录等）
- **无硬件测试**：所有单元测试与集成测试的默认运行环境，不依赖任何物理设备或串口

### 链路组成

| 层 | 实现 |
| --- | --- |
| Hardware Device Layer | `device.simulator.SimulatorDevice` —— 通过可配置的 `ValueGenerator`（常量/序列/随机）主动生成数据，无需外部输入 |
| Communication Layer | `communication.loopback.LoopbackChannel` —— 基于内存队列的回环通道，`send()` 之后可通过 `receive()` 取回，模拟双向通信 |
| Protocol Layer | `protocol.encoder`/`protocol.decoder`（与 Hardware 模式完全相同） |

### 已验证的能力

Simulator 模式已完成从 `SimulatorDevice` 生成数据、经 `Protocol` 编解码、通过 `LoopbackChannel` 收发、由 `Service Layer` 分发、经 `API Layer` 转发、最终在 `PyQt6 UI` 实时展示的完整闭环（见 `tests/integration/`、`tests/ui/`）。

## Hardware 模式

### 用途

- **MCU 真实数据接入**：未来接入真实嵌入式设备（如 STM32、MSPM0）时使用，设备通过 UART/USB/蓝牙等物理链路上报数据、接收指令

### 链路组成

| 层 | 实现 |
| --- | --- |
| Hardware Device Layer | `device.remote.RemoteDevice` —— 只维护 `device_id`/`capability`/`status`，**不主动生成任何数据**，不包含任何串口逻辑，不依赖 `communication` |
| Communication Layer | `communication.serial.SerialChannel` —— 基于 pyserial 的真实串口实现（`connect`/`disconnect`/`send`/`receive`），已在通信层第二阶段完成 |
| Protocol Layer | `protocol.encoder`/`protocol.decoder`（与 Simulator 模式完全相同） |

### 当前阶段范围（重要）

已完成（软件架构 + 数据/命令双向链路，且已通过硬件在环演示验证，见下方"已验证的能力"）：

- `RemoteDevice` 类型定义与 `DeviceInterface` 结构化匹配
- `DeviceManager.register()` 同时接受 `SimulatorDevice` 与 `RemoteDevice`
- `DeviceManager.report_data()` 明确拒绝对 `RemoteDevice` 调用（真实设备的数据不应该被"生成"，而应来自真实读取）
- **数据上行**：`HardwareDeviceReceiver`（`src/application/hardware_runtime.py`）从 `SerialChannel` 持续读取字节、拼帧、解码，写回对应 `RemoteDevice` 的 `DataService`——字节流没有消息边界（不同于 `LoopbackChannel`），拼帧/断帧由 `application/frame_stream.py`（`FrameStreamBuffer`）统一处理
- **命令下行**：`DeviceManager.deliver()` 对 `RemoteDevice` 会真正等待设备侧发回的 `COMMAND_ACK_CODE` 应答帧（带超时），见下方"命令下发：Simulator 与 Hardware 的两条路径"

**不包含**：

- 任何真实 MCU 固件代码（`scripts/virtual_stm32.py` 是纯软件模拟的虚拟设备，用于在没有真实硬件时验证上面两条链路，见 `docs/05_Test/Virtual_STM32_Test.md`）
- `RemoteDevice.status` 随真实连接建立/断开而自动更新的机制（当前只提供 `with_status()` 方法供未来调用，本身不会主动触发）

### 已验证的能力（Hardware 模式）

2026-08-12 已通过 WSL2 + socat 虚拟串口对完成一次完整的硬件在环演示（详见 `docs/05_Test/status/早期归档.md`，2026-09-09 前为 `Project_Status_Context.md` 第 10 节）：`scripts/virtual_stm32.py`（虚拟设备）与 `scripts/run_gui.py --mode hardware`（真实 GUI）之间，经真实字节流（不是内存 mock）验证了：

- 数据上行：temperature/humidity/noise 三通道持续上报，界面实时更新
- 命令下行：GUI"发送命令"能收到虚拟设备的真实应答，超时/无应答时优雅失败（`api.exceptions.CommandDeliveryError`）而不是崩溃或挂起

### 命令下发：Simulator 与 Hardware 的两条路径

`DeviceManager.deliver()`（`CommandTransport` 的实现）根据 `registration.device` 是否实现 `generate()`（即是否为 `SimulatorDevice`）分两条路径，二者共享同一个对外方法签名，`service`/`api`/`ui` 无需区分：

| | Simulator（`SimulatorDevice`） | Hardware（`RemoteDevice`） |
| --- | --- | --- |
| 实现方法 | `_simulate_device_ack()` | `_await_device_ack()` |
| 应答来源 | `DeviceManager` 自己在本地"自问自答"——发送请求后立即读回自己的请求（丢弃），按 `registration.accepted_commands` 在本地构造 ack 并发送、再读回；只对 `LoopbackChannel` 这种"发送即可读回"的回环通道成立 | 真正等待设备（真实固件或 `virtual_stm32.py`）主动发回的 `COMMAND_ACK_CODE` 帧；接受/拒绝由设备自己决定，`accepted_commands` 对 Hardware 模式不生效 |
| 超时 | 不适用（本地操作，瞬间完成） | 有（phase-1 为 2 秒），超时抛 `core.exceptions.OperationTimeoutError`，经 `api/local_api.py` 转译为 `api.exceptions.CommandDeliveryError` |
| 字节流处理 | 不需要（`LoopbackChannel` 按 `send()` 调用保留消息边界） | 需要，使用 `application/frame_stream.py` 的 `FrameStreamBuffer` 正确处理帧粘连/半帧 |

**已知的 phase-1 折中**：`_await_device_ack()` 等待期间，如果收到的帧不是期望的 ack（最常见是与命令同时到达的 `DATA_REPORT` 帧），会被跳过丢弃，不转发给 `HardwareDeviceReceiver`——即命令往返期间最多丢一条传感器读数。这是为了不需要在 `DeviceManager` 与 `HardwareDeviceReceiver` 之间共享一个接收循环而接受的折中，等未来有真实的多设备/高频场景需求时再重新设计。

### 阈值报警：Simulator/Hardware 两种模式统一接入 UI（2026-08-12）

`SensorDataProcessor`（`src/service/sensor_data_processor.py`）此前是完全独立、未接入 `api`/`ui` 的组件（统计/报警结果算出来了但界面看不到）。这次任务把它正式接入了整条链路，Simulator 与 Hardware 两种模式**共用同一套接入逻辑**：

- `ApplicationRuntime` 内部持有一个 `SensorDataProcessor`（`_alarm_processor`），通过新增的 `watch_alarms_for(device)` 方法，按 `device.capability.channels` 自动把每个通道接入报警评估——不需要调用方（无论是 `ui` 用户点了"订阅"，还是别的什么）做任何额外操作，因为报警应该在任何人查看之前就已经在评估
- `ApplicationRuntime.register_device()`（facade 方法）会自动调用 `watch_alarms_for()`；但 `scripts/run_gui.py` 的 `build_hardware_runtime()` 因为需要拿到 `DeviceRegistration.wire_id`，绕开了这个 facade、直接调用 `runtime.devices.register(...)`，所以**必须自己再显式调用一次 `runtime.watch_alarms_for(device)`**——这是本次任务里一个真实踩过的坑（2026-08-12 硬件在环演示时，报警在 Simulator 模式测试正常，切到 Hardware 模式后完全不触发，才发现 `build_hardware_runtime()` 漏掉了这一步），已修复并补了回归测试（`tests/scripts/test_run_gui.py::test_hardware_mode_device_channels_are_watched_for_alarms`）。**教训**：任何"注册设备"相关的新逻辑，都要同时检查 `ApplicationRuntime.register_device()`（Simulator 路径走这里）和 `scripts/run_gui.py::build_hardware_runtime()`（Hardware 路径绕开 facade 直接调用 `DeviceManager.register()`）两处是否都需要同步更新，不能只改一处就认为两种模式都覆盖到了
- `SensorDataProcessor` 新增 `on_status(callback)`/`ThresholdStatus`，与原有的 `on_alarm(callback)`/`AlarmEvent` 并存、互不影响：`on_alarm` 只在真正超限时触发（不变，原有测试全部沿用）；`on_status` 对每一个评估过阈值规则的读数都触发（无论超限与否），多出的 `triggered: bool` 字段是 UI 侧"恢复正常颜色"功能的关键——只有 `on_alarm` 的话，UI 永远不知道"什么时候该把红色改回来"
- `api.interface.ApiInterface` 新增 `subscribe_alarm_status(callback)`（全局订阅，不分设备/通道，没有配套的 unsubscribe），是这次任务里**唯一** touch 到的受保护接口文件，属于纯新增方法、不改变任何已有方法签名
- UI 呈现：`ui/widgets/control_panel.py` 的活动日志追加红色报警条目（只在 `triggered=True` 时记一条，避免刷屏）；`ui/widgets/data_panel.py` 对应行标红/清除（`triggered` 为 True/False 直接驱动，不依赖信号到达顺序）

已在 WSL 硬件在环环境中手动验证：临时把 `TEMPERATURE_ALARM_MAX` 调低到 26℃（因为演示时温度一直在 25℃ 左右徘徊，等自然超过 35℃ 太慢），确认报警变红、日志追加、降回阈值以下后自动恢复颜色，均正常；验证后已改回 `35.0`。

### 统计信息：复用报警接入的同一套机制（2026-08-12，同一天稍晚）

`SensorDataProcessor.get_statistics()`（当前值/最小值/最大值/平均值/样本数）此前也是"算出来了但界面看不到"的状态，接入方式与阈值报警几乎一样：

- `SensorDataProcessor` 新增 `on_statistics(callback)`/`ChannelStatistics` 推送式回调，`handle_data_point()` 内部本来就在维护统计（`_RunningStatistics`），这次只是多加一步把快照推给回调——不像 `on_status` 只对 temperature/humidity/noise 三个有阈值规则的 channel 触发，`on_statistics` 对**任意**数值 channel 都触发
- `ApplicationRuntime.subscribe_statistics(callback)` 直接复用了报警接入时已经修好的 `watch_alarms_for()` 自动订阅（同一条 `_alarm_processor.subscribe_to()` 订阅，`handle_data_point()` 现在同时服务报警评估和统计推送两个用途）——这意味着 Hardware 模式**这次不需要重新踩一遍上面记录的那个坑**，`build_hardware_runtime()` 已有的 `runtime.watch_alarms_for(device)` 调用自动就把统计也覆盖了，实现前就确认过这一点，未再引入新 bug
- `api.interface.ApiInterface` 新增 `subscribe_statistics(callback)`（第二个纯新增的受保护接口方法，全局订阅，同样没有配套的 unsubscribe）
- UI 呈现：新增独立 widget `ui/widgets/statistics_panel.py`（`StatisticsPanelWidget`）——刻意做成与 `DataPanelWidget` 的实时数据表格**分开**的表格，而不是在原表格里加列，理由是统计（跨整个通道历史的聚合值）和实时值（单次读数）是不同的概念，分开保持每个 widget 职责单一。列为：设备/通道/当前值/最小值/最大值/平均值/样本数，按 (device_id, channel) 逐行更新

已在 WSL 硬件在环环境中手动验证：订阅后统计信息面板正常显示并实时更新。

## 未来 MCU 只需实现的最小集合

真实 MCU（如 STM32）接入本系统时，**不需要了解本项目的 Python 代码结构**，只需要在固件侧实现以下五项，与本项目已定义的协议规范（`docs/03_Communication/Protocol_Design.md`、`src/protocol/`）保持一致：

1. **UART/USB/BLE 等字节传输**：能够通过某种物理链路可靠地收发字节流（本项目 PC 侧对应 `SerialChannel`，串口参数如波特率需与固件配置一致）
2. **Protocol 帧格式**：按 `帧头(0xAA 0x55) + 设备ID(1字节) + 命令类型(1字节) + 数据长度(2字节大端) + Payload + CRC(4字节)` 的格式收发帧（见 `src/protocol/encoder.py`/`decoder.py` 中的具体位宽定义）
3. **Device ID**：固件侧对自身设备 ID（0-255 范围内的数值）有固定认知，与 PC 侧 `DeviceManager` 为该设备分配/约定的 wire id 一致
4. **Command Type**：能够识别 PC 下发的命令类型编码，并针对已知命令做出对应处理，未知命令类型应予以拒绝而非静默忽略；**处理完成后必须回复一条 `COMMAND_ACK_CODE`（`0x02`）帧**（`device_id` 与收到的命令一致，Payload 为 `{"status": "success"｜"failed"}`），否则 PC 侧 `DeviceManager.deliver()` 会在超时后判定命令投递失败——这一点已通过 `scripts/virtual_stm32.py` 的命令监听/应答逻辑验证，见 `docs/03_Communication/Protocol_Design.md`"命令类型 phase-1 内部约定"一节与 `docs/05_Test/Virtual_STM32_Test.md`
5. **Payload 解析与 CRC 校验**：能解析 Payload 中的内容，并对收到的帧执行 CRC 校验，校验失败时按 `Protocol_Design.md` 的规范处理（丢弃该帧、不尝试"修复"）

   > **实际结论（2026-08-16 实机验证，2026-09-07 更正本条）**：本条原写作"具体格式取决于后续为
   > Hardware 模式设计的负载约定，当前 Simulator 模式使用的 JSON 约定仅是 PC 侧内部实现细节，
   > 不代表 Hardware 模式必须沿用同一格式"。实际落地时 **STM32 固件沿用了同一套 JSON 约定**
   > （`firmware/stm32f407/User/main.c` 的 `report_channel()` 以 `snprintf` 拼出
   > `{"channel":"...","value":...}`，通道字符串与 `src/device/sensors/channels.py` 完全一致），
   > 两种模式因此共用同一份 payload 约定，`HardwareDeviceReceiver` 无需为 Hardware 模式另写解析分支。
   > 是否改为紧凑二进制格式曾长期列为待评估项，现已结案不再作为后续方向（见
   > `Project_Status_Context.md` 5.8 节）。

满足以上五点后，PC 侧只需将 `SimulatorDevice` 替换为一个持有该设备 `device_id`/`capability` 的 `RemoteDevice` 实例，并将 `LoopbackChannel` 替换为指向真实串口的 `SerialChannel` 实例注册进 `DeviceManager`，Protocol Layer 及以上的全部代码（`service`/`api`/`ui`）无需任何改动即可工作。

## 相关文档

- `docs/02_Architecture/System_Architecture.md`
- `docs/02_Architecture/Core_Service_Design.md`（第 1、6 节）
- `docs/03_Communication/Protocol_Design.md`
- `docs/03_Communication/Communication_Design.md`
- `docs/05_Test/Test_Plan.md`
