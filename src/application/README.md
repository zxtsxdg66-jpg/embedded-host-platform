# application

## 职责

`application` 是新增的组合根/运行时模块：将 `device`、`protocol`、`communication`、`service` 串联为一个无真实硬件即可运行的数据/控制闭环，对应 `docs/02_Architecture/Core_Service_Design.md` 第 4 节 Service Layer 中"设备生命周期管理"职责，以及 `protocol/README.md` 中标注的"Service Layer 字符串 DeviceId 与 Frame 数值型 device_id 之间的映射"这项后续桥接工作。

已实现：

- `manager.py`：`DeviceManager` —— 设备注册（同时支持 `SimulatorDevice` 与 `RemoteDevice`，二者均结构化满足 `DeviceInterface`）、device_id(str) ↔ Frame.device_id(int) 映射、上行数据帧编解码、下行指令帧编解码；同时结构化满足 `service.control_service_impl.CommandTransport` 契约。`deliver()` 按设备类型分两条路径：`SimulatorDevice`（`_simulate_device_ack`）在本地自问自答（只对 `LoopbackChannel` 成立）；`RemoteDevice`（`_await_device_ack`）真正等待设备侧发回的 `COMMAND_ACK_CODE` 帧，带超时，超时抛 `core.exceptions.OperationTimeoutError`。详见 `docs/05_Test/Hardware_Simulation_Mode.md`"命令下发：Simulator 与 Hardware 的两条路径"
- `frame_stream.py`：`FrameStreamBuffer` —— 从没有消息边界的字节流（`SerialChannel`）中正确切出完整帧，处理帧粘连/半帧/脏字节重同步；被 `hardware_runtime.py`（数据上行）与 `manager.py` 的 `_await_device_ack`（命令下行等待）共用，不依赖任何具体 Device/CommunicationChannel 实现
- `runtime.py`：`ApplicationRuntime` —— 组合 `DeviceManager` + `InMemoryDataService` + `InMemoryControlService` + `SensorDataProcessor`（内部持有，`_alarm_processor`，同时服务报警与统计两个用途）的门面，提供 `register_device`/`subscribe`/`report_data`/`acquire`/`release`/`submit_command`/`get_result`/`subscribe_alarm_status`/`subscribe_statistics`/`watch_alarms_for`（均 2026-08-12 新增，见下）。2026-09-07 起还持有第二个按通道处理的组件 `VentilationController`（`_ventilation`）与可选的 `FanCommandDispatcher`（`_fan_dispatcher`），新增门面方法 `enable_fan_control`/`fan_dispatcher`/`subscribe_fan_decision`/`get_ventilation_settings`/`set_ventilation_thresholds`/`set_fan_mode`；同日稍后又新增 `enable_alarm_state_mirroring`/`alarm_state_dispatcher`（板载 LCD 的报警状态镜像）；`watch_alarms_for` 已改名为 `watch_device_channels`（同时订阅报警与通风两个处理器），**旧名保留为别名**以免既有组合脚本漏订阅
- `fan_dispatcher.py`：`FanCommandDispatcher` —— 2026-09-07 新增，把 `service.ventilation_controller` 产出的 `FanDecision` 变成真正下发到设备的指令。**决策与发送刻意拆成两个方法**：`handle_decision()` 只记录期望状态、**不发送任何东西**（它跑在 `DataService` 发布回调链上）；`dispatch_pending()` 才真正下发，由组合根在轮询循环里紧挨着 `runner.run_once()` 调用。
  - **这个拆分不是风格问题**：最初写成在 `handle_decision()` 里直接发送，在 Hardware 模式下是不安全的——该回调是由 `HardwareRuntimeRunner.run_once()` 读串口的过程中触发的，此时再下发命令会**重入** `DeviceManager.deliver()`，而它的 RemoteDevice 分支要读**同一个串口**等应答、还用着另一个 `FrameStreamBuffer`。两个读者抢同一条流会互相吃掉帧，整个往返还会卡住调用方的定时器回调。这不是理论推演：2026-09-07 实测直接把测试进程打崩（pytest-qt 处理事件时 `Fatal Python error: Aborted`），真机上则会在等应答期间冻结界面并丢掉传感器读数。
  - 其余三件事：**去重**（控制器每条读数都发决策，只在期望状态变化时才下发）、**占用**（自动通风不是争抢设备的客户端，故"下发前 acquire、下发后立即 release"，若有人类客户端持有设备则本轮让位——手动优先）、**免费重试**（失败时不更新 `applied_state`，下个轮询周期自然重试，无需定时器）。
  - `applied_state` 初值为 `False` 而非 `None`：固件上电时风扇是停的，据此假设可避免每次启动都白发一条 `FAN_OFF`。
  - 失败只计数不外抛（`dispatch_count`/`deferred_count`/`failure_count`/`last_error`），与 `hardware_runner.py` 一致
- `alert_dispatcher.py`：`AlertCommandDispatcher` —— 2026-09-07 新增，把 `service.alarm_announcer` 的播报决定变成设备指令。与 `fan_dispatcher` 同样是"`handle_announcement()` 只记录、`dispatch_pending()` 由轮询循环发送"，原因完全相同（重入串口）。差别在于风扇命令携带的是**状态**、播报是**事件**：因此没有"与上次已应用值去重"这回事；且**真正发出过的请求失败后不重试**——下个轮询周期时报警已是几秒前的事，迟到的播报比不播更糟；而"被让位"（有人类客户端持有设备、根本没发出去）会保留待下轮重试。若两次轮询之间来了多条播报请求，只保留最后一条
- `alarm_state_dispatcher.py`：`AlarmStateDispatcher` —— 2026-09-07 新增（LCD 一并引入），把 `SensorDataProcessor` 的逐条阈值评估折叠成一个**每通道是否报警的位图**下发给设备，供板载 LCD 显示"正常/报警"。与另外两个派发器同样遵守"回调只记录、`dispatch_pending()` 才发送"，原因相同（重入串口）。结构上跟 `fan_dispatcher` 而不是 `alert_dispatcher`——报警状态是**状态**不是事件，所以要与已应用值去重、失败要重试。**它是三个派发器里唯一没有对应 `service/` 决策组件的**：位图只是既有阈值评估结果的换一种说法，没有任何策略可以拆出去，硬拆只会造出一个行为只有 `|=` 的类。阈值本身不复制到固件，理由见 `docs/03_Communication/Protocol_Design.md` 的 `ALERT_STATE` 小节。
- `history_recorder.py`：`HistoryRecorder` —— 2026-09-17 新增，订阅 `DataService` 的读数并**攒批**交给 `service.history.HistoryStore` 落盘。与三个派发器同样遵守"回调只记录、轮询循环才动手"，但这里不是偏好而是硬约束：`InMemoryDataService.publish()` 是同步的，回调跑在采集线程上，而该线程下一步就是取模型结果——磁盘写放进去就直接坐在维持界面响应的那条路径上。满 50 条或距最早一条超过 5 秒才写，退出前 `flush()`。`DataPoint.value` 是 `Any` 且硬件与 Modbus 两条路径都由 `json.loads(...)["value"]` 构造，因此非数值读数**计数而不抛**（`skipped`），坏帧不会连累同批其它读数。设计见 `docs/02_Architecture/History_And_Cloud_Design.md` 第 4.2 节
- `answer_dispatcher.py`：`AnswerDispatcher` —— 2026-09-08 新增（2026-09-14 补记于本文件），把环境问答的最近一条答案下发到板载 LCD 第二页，命令码 `ANSWER_SHOW`（`0x16`）。形状与 `alarm_state_dispatcher` 相同（回调只记录、`dispatch_pending()` 由轮询循环发送）。**下发的不是文本，是"哪一类答案 + 数值"**：板载字库只是 `ui_screen.c` 字面量生成的子集，画不出任意中文句子，由板子按自己的模板渲染。因此模型怎么改写措辞都不影响屏幕内容；没有对应模板的答案（帮助、反问、指令）不下发。PC 与手机的提问同等处理，并标记来源。设计见 `docs/02_Architecture/Assistant_Design.md`，协议见 `docs/03_Communication/Protocol_Design.md`
- `simulator_runner.py`：`SimulatorRuntimeRunner` —— 2026-08-14 新增（2026-09-14 补记于本文件），Simulator 模式的周期驱动器，是 `hardware_runner.py` 的对应物且形状一致：不启线程、不用 asyncio、不内部循环，只提供 `run_once()` 供外部驱动方（`QTimer`、脚本循环、测试）按 `poll_interval_seconds` 调用，内部调 `ApplicationRuntime.report_data()`。存在的原因：此前 `report_data()` 只在测试里被调用过，模拟模式实际从未产生过数据（2026-08-14 实测确认）。`run_once()` 不外抛，单通道失败只计数
- `hardware_runtime.py`：`HardwareDeviceReceiver` —— Hardware 模式的数据**接收**链路：持续从 `CommunicationChannel`（生产环境为 `SerialChannel`）`receive()`，用 `frame_stream.FrameStreamBuffer` 正确处理没有消息边界的字节流（一次 `receive()` 可能读到多帧粘连或半帧），经 `protocol.decode()` 解析出 `DATA_REPORT` 帧，转换为 `DataPoint` 并 `DataService.publish()`。独立于 `DeviceManager`/`ApplicationRuntime` 的设备注册表，`wire_id` 由调用方直接给定
- `hardware_runner.py`：`HardwareRuntimeRunner` —— 包一层 `start()`/`stop()`/`running`/`run_once()` 状态管理在 `HardwareDeviceReceiver` 外面，`poll_interval_seconds` 只是暴露给外部驱动方（如 `QTimer`）的配置值，自身**不启线程、不用 asyncio、不内部循环**；"持续运行"由调用方（`scripts/run_gui.py` 里的 `QTimer.timeout.connect(runner.run_once)`）负责，未修改 `hardware_runtime.py` 一行代码
- `link_monitor.py`：`LinkMonitor`，2026-09-23 新增，串口链路的**观测点**。`HardwareDeviceReceiver` 可选接收一个 monitor（`monitor=None` 时行为与之前完全相同），在拼帧与解码的各个分支上报事件：`frame`（正常帧）、`resync`（丢弃脏字节重新同步）、`checksum_error`（CRC 不符）、`decode_error`（帧格式错）、`ignored`（非本设备或非数据帧）、`payload_error`（载荷不是合法读数），并累计收到的字节数。`LinkEvent` 携带原始字节、设备号、命令码、载荷与说明，`LinkStatistics` 是各计数的快照。`ApplicationRuntime` 持有一个实例（`link_monitor`），经 `get_link_statistics()`/`subscribe_link_events()` 向 `api` 暴露；`active` 为假表示当前模式没有字节流（Simulator）。**它只观测、不参与判断**：拼帧与校验仍全部由 `frame_stream`/`protocol` 完成，监视器只是把原本只计数的分支报告出来。供 Web 控制台的串口链路页使用，设计见 `docs/02_Architecture/Web_Console_Design.md` 第 5 节
- `scripts/run_gui.py`（不在本目录，但组合本目录的类）已实现 `build_hardware_runtime(port, baudrate, device_id)`：用 `runtime.devices.register(...)` 直接拿到 `DeviceRegistration.wire_id` 来构造 `HardwareDeviceReceiver`，详见该脚本与 `docs/05_Test/Runtime_Mode.md`。**因为绕开了 `register_device()` facade，它必须自己再显式调用一次 `runtime.watch_alarms_for(device)`**——2026-08-12 曾漏掉这一步，导致 Hardware 模式下报警从未被评估过，已修复并补了回归测试（`tests/scripts/test_run_gui.py::test_hardware_mode_device_channels_are_watched_for_alarms`）；任何"注册设备后要做的事"都要同时检查这两处

`ApplicationRuntime.watch_alarms_for(device)`：按 `device.capability.channels` 把 `_alarm_processor`（`SensorDataProcessor`）自动订阅到该设备的每个通道，`register_device()` 内部会调用它，`build_hardware_runtime()` 需要单独调用（见上）。`subscribe_statistics()` 复用的是同一条订阅——`SensorDataProcessor.handle_data_point()` 本来就在维护统计，只是多加了一步回调，所以 Hardware 模式不需要为统计再单独修一次 bug

Simulator 模式与 Hardware 模式的对比说明见 `docs/05_Test/Hardware_Simulation_Mode.md`；两种模式最终都汇入同一个 `DataService`，下游的 `SensorDataProcessor`/`ui.controller.MainController` 无需区分数据来源。启动方式（含 `--mode hardware --port COM3` 参数）见 `docs/05_Test/Runtime_Mode.md`。

## 设计约束

- 不包含任何 PyQt/Android 代码，是未来 UI/`api` 层的下方支撑
- 不绑定具体传感器、控制对象或 MCU 型号
- 全程同步执行（发送与接收在同一方法调用内完成），呼应 `communication/interface.py` 中"异步/事件驱动收发延后到后续阶段"的说明
- `report_data()`（软件生成数据）只对实现了 `generate()` 的设备（`SimulatorDevice`）生效；`RemoteDevice` 调用会抛出 `ValidationError`，因为真实设备的数据应来自未来的串口读取循环，而非被动"生成"

## 依赖关系

依赖 `core`、`device`、`protocol`、`communication`、`service`。不被任何其他模块依赖（`api`/`ui` 未来可能依赖它）。

## 相关文档

- `docs/02_Architecture/System_Architecture.md`
- `docs/02_Architecture/Core_Service_Design.md`（第 4、6 节）
