# service

## 职责

`service` 实现 `docs/02_Architecture/Core_Service_Design.md` 定义的 **Service Layer**，是 Application Layer 中承上启下的核心部分。

已实现：

- 数据/指令模型：`data_models.py`、`command_models.py`
- 基础接口：`data_service.py`（`DataService`）、`control_service.py`（`ControlService`）
- 具体实现（第一阶段）：
  - `data_service_impl.py`：`InMemoryDataService` —— 同步进程内订阅/分发
  - `control_service_impl.py`：`InMemoryControlService` —— "共享读、独占写"占用规则 + 通过注入的 `CommandTransport` 契约完成指令派发；实际的协议/通信桥接由 `application.manager.DeviceManager` 提供（见该模块）
- `sensor_data_processor.py`：`SensorDataProcessor` —— 传感器应用模拟验证阶段新增，订阅 `DataService` 发布的 `DataPoint`，维护每个 (device_id, channel) 的当前值/最大值/最小值/平均值（`get_statistics()`），并对温度/湿度/噪音三个已知 channel 做阈值判断（2026-09-08 起规则表由"一通道一条单边规则"改为 `AlarmBand` 区间，两侧边界均可缺省：湿度 30~75 %RH 双向，温度 >35 ℃、噪声 >80 dB 仍是单边）。三套回调并存：`on_alarm()`（只在超限时触发）、`on_status()`（2026-08-12 新增，每次评估都触发，携带 `triggered: bool`，供接入方判断"何时恢复正常"，仅限有阈值规则的 3 个 channel）、`on_statistics()`（同日新增，对**任意**数值 channel 触发，携带 `ChannelStatistics` 快照）。数据流：`SensorSimulator → DataService → SensorDataProcessor → (application.ApplicationRuntime.watch_alarms_for 自动订阅) → api.subscribe_alarm_status/subscribe_statistics → ui`——报警与统计均已于 2026-08-12 接入界面（见 `docs/05_Test/Hardware_Simulation_Mode.md`"阈值报警"/"统计信息"两节）

- `ventilation_controller.py`：`VentilationController` —— 2026-09-07 新增，与 `SensorDataProcessor` 结构对称（`handle_data_point` 同样匹配 `DataCallback`，可直接作为 `DataService` 订阅者），但回答的是**另一个问题**：`SensorDataProcessor` 回答"要不要提醒人"（阈值取自 GB 37488—2019，论文已论证，**固定不可改**），本模块回答"风扇该不该转"（阈值**可运行时调整**，且语义相反——报警规则里湿度是"过低"报警，而通风需要的是"过高"时启动；实测湿度长期 69~95%RH，报警规则实际从未触发）。两者分开使论文既有论证不受影响。支持 `FanMode.AUTO/MANUAL_ON/MANUAL_OFF` 手动覆盖；**只决策、不执行**（不构造 `Command`、不碰 `ControlService`），把决策变成指令是 `application.fan_dispatcher.FanCommandDispatcher` 的职责。`on_decision` 与 `on_status` 一样**每条读数都触发**（不只在状态跳变时），便于界面持续渲染当前状态与原因；跨设备取各通道最大值，因此 Simulator 模式（温湿度来自两台设备）与 Hardware 模式（同一台）共用同一份实现

- `alarm_announcer.py`：`AlarmAnnouncer` —— 2026-09-07 新增，决定**何时该把阈值报警念出来**。两道闸门：**连续确认**（默认连续 2 个采集周期超限才算数，拒绝单个尖峰，同时落实了论文第 10 章已列的"引入持续时间确认"改进方向）与**冷却**（默认 30 秒）。冷却是**跨通道全局的**——只有一个喇叭，三个通道依次排队播报正是这道闸门要防的失控；代价是温度播报后 30 秒内噪声超限不会出声，属有意取舍（报警在界面与活动日志里仍然可见）。时钟可注入，便于测试不 sleep。同样**只决策不执行**，把决定变成指令是 `application.alert_dispatcher` 的事

尚未实现（不在本次范围内）：

- 设备发现、能力协商等更完整的设备生命周期管理（当前由 `application.manager.DeviceManager` 承担最小子集）
- 网关模式下的集中部署形态（详见 `Core_Service_Design.md` 第 4.3 节）

## 设计约束

- 不做协议帧编解码（`protocol` 职责）、不做物理连接管理（`communication` 职责）、不做界面渲染（`ui` 职责）
- 不预设具体业务规则（如某类数据的阈值判断），只提供数据与指令的通道能力
- 直连模式下运行于客户端本地进程；网关模式下可集中部署（详见 `Core_Service_Design.md` 第 4.3 节），两种部署形态下对外暴露的概念模型必须一致

## 依赖关系

依赖 `core`、`device`、`protocol`；被 `api`、`ui` 依赖。

## 相关文档

- `docs/02_Architecture/Core_Service_Design.md`
- `docs/02_Architecture/Multi_Client_System_Architecture.md`

## `assistant/` 子包（2026-09-08 新增）

环境问答的三层管线，设计见 `docs/02_Architecture/Assistant_Design.md`。

- `models.py`：`Intent` / `Facts` / `Answer`。**`Facts` 是结构化对象，不是拼好的句子**——它有多个消费端（面向人的措辞、将来面向板载 LCD 的推送），一旦产出字符串就只能喂给其中之一。
- `intent.py`：规则意图匹配。中文没有词边界，因此用子串包含而非正则；识别不出的问句落到 `HELP`，宁可列出会答什么，也不猜一个通道去自信地答错。
- `retrieval.py`：**唯一产生数字的地方**。读 `SensorDataProcessor` 与 `VentilationController`，阈值直接引用该模块的公开常量，不另抄一份数值。多设备同通道时按该通道自己的 `AlarmBand` 取"最差"的那个——离区间最远的那个读数，两侧都算；全部在区间内时取离边界最近的。
- `phrasing.py`：模板渲染 + `numbers_are_grounded()`。后者是本功能核心保证的**运行时兜底**：提示词只是请求，不是约束，所以在出口处逐个核对——答案里的每个数字都必须能在 `Facts` 里找到，否则丢弃模型版本、改用模板。
- `llm_port.py`：`LlmClient` 协议 + `NullLlmClient`。**协议定义在消费方**，与 `CommandTransport` 定义在 `control_service_impl.py` 的既有约定一致；具体实现在 `src/llm/`，由组合根注入。
- `assistant.py`：门面。`ask()` 同步返回模板答案（纯计算，无 I/O），模型结果由 `poll_rephrasing()` 在轮询循环里取回。
- `assistant/control.py`：**指令**的执行层（开/关/自动风扇、改通风阈值四项白名单）。只写 `VentilationController` 的设置，不构造命令、不碰串口——与界面上点一下是同一次写入；阈值数值从**用户原话**里正则取，绝不取自模型回复。
- `assistant/parsing.py`：**规则落空时**才调用的模型分类层——模型只回一个标签，答案仍由取数 + 模板生成；回复不可用则保持帮助文案不变。设计见 `docs/02_Architecture/Assistant_Design.md` §12。

**模型是可选的**：没装、没起、超时、被卸载，问答照常工作，只是措辞死板一些。这与"AHT20/ES8388/LCD 任一外设缺失都不让整机停摆"是同一条处理原则。
