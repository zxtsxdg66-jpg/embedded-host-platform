# 架构

## 包的划分

`src/` 下 11 个包。概念上是经典的五层（硬件设备 / 通信 / 协议 / 应用 / 界面），
落到代码时把支撑与桥接职责拆了出来，并为"接外部资源"的适配层各开一个包。

| 包 | 职责 |
| --- | --- |
| `core` | 共享基础类型：id 别名、异常基类、时间戳、通道展示约定、链路事件值类型。被所有包依赖，不依赖任何包 |
| `device` | 设备抽象 `DeviceInterface`，模拟设备 `SimulatorDevice`，真实设备的占位 `RemoteDevice`，传感器数值模型 |
| `protocol` | 帧结构、编解码、CRC-32。与通信介质无关 |
| `communication` | 字节收发契约 `CommunicationChannel`，及其实现：回环、串口、管道 |
| `service` | 业务逻辑：数据分发、控制权、阈值报警与统计、通风决策、报警播报、问答管线 |
| `application` | 组合根与运行时：设备注册与 id 映射、字节流拼帧、两种接收循环、把决策变成设备指令的派发器、历史记录 |
| `api` | `ApiInterface`，所有呈现端唯一的入口 |
| `ui` | PyQt6 桌面端（控制器 + 窗口 + 部件） |
| `gateway` | 无界面的 REST + WebSocket 网关，给 Android 与浏览器用 |
| `llm` | 本地语言模型服务的客户端（Ollama），非阻塞 |
| `storage` | 本地历史库（SQLite）与对象存储上传器 |

仓库顶层另有三个独立工具链的目录，与 `src/` 互不 import：`firmware/`（Keil + STM32 HAL）、
`android/`（Gradle + Kotlin）、`web/`（原生 JS，网关的客户端）。

## 依赖规则

```
        ui        gateway            ← 两个平级呈现端
          \        /
             api                     ← 统一门面
              |
         application                 ← 组合根：唯一创建具体适配器的地方
        /   |    |   \
  service protocol communication  llm  storage
      |
    device

  core                                ← 被所有包依赖，不依赖任何包
```

每个包可以依赖哪些包是一张白名单，写在
[`tests/architecture/test_layering.py`](../tests/architecture/test_layering.py) 里。
测试用 `ast` 读 `src/` 下每个文件的每一条 import（包括函数内部与类型检查块里的），与白名单比对。
除此之外还核对三条更细的规则：

- **呈现端只拿模型类型。** `ui` 与 `gateway` 可以 import `service`，但只限 `ApiInterface`
  签名里出现的那几个模型模块——这个集合直接从 `api/interface.py` 的 import 读出来，不另写一份
- **界面里只有控制器碰外面。** `ui/` 中除 `controller.py` 以外的文件不得 import `api` 或 `service`
- **网关不依赖 GUI 框架。** `gateway` 不得 import PyQt6

这个测试设立的当天就查出一处违规：`gateway` 为了两个值类型直接 import 了 `application`，
随即把类型挪进 `core`。**写在文档里、没有东西检查的规则，迟早会漂移。**

### 端口定义在消费方

`service` 需要语言模型、需要持久化，但不 import `llm` 与 `storage`。它自己定义需要的协议：

```python
# service/assistant/llm_port.py
class LlmClient(Protocol):
    def submit(self, prompt: str, system: str = "") -> bool: ...   # 立即返回，不等结果
    def poll(self) -> str | None: ...                              # 由轮询循环来取
    def is_busy(self) -> bool: ...
    def cancel(self) -> None: ...
```

`llm.OllamaClient` 与 `storage.SqliteHistoryStore` 结构化地满足这些协议，由 `application`
或 `scripts/` 的组合代码创建并注入；没有模型或不需要持久化时注入 `NullLlmClient` /
`NullHistoryStore`。换一个模型服务、换一种存储，`service` 一行不改；
测试里注入一个脚本化的假实现即可。

模型客户端是"提交、之后再取"的形状而不是一次阻塞调用，是因为问答跑在采集线程上：
一次推理要几秒，阻塞调用会让这几秒里的读数全部停住。

## 三种运行模式，同一套上层代码

| | 设备 | 通道 | 接收 |
| --- | --- | --- | --- |
| simulator | `SimulatorDevice`（主动生成数据） | `LoopbackChannel` | 设备管理器直接编解码 |
| virtual | 进程内虚拟 STM32（`scripts/virtual_stm32.py`） | `PipeChannel` 管道 | `HardwareDeviceReceiver` |
| hardware | `RemoteDevice`（只描述，不产生数据） | `SerialChannel` | `HardwareDeviceReceiver` |

三者在 `DataService.publish()` 汇合，从这里往上（报警、统计、通风、问答、历史、`api`、所有呈现端）
**没有任何一处判断当前是哪种模式**。差异全部在组合代码里：`scripts/run_gui.py`、
`scripts/run_api_server.py` 各有 `build_*_runtime()` 函数负责装配。

virtual 模式存在的原因是回环通道的一个性质：它把每次 `send()` 原样作为一次 `receive()` 交回，
**保留了消息边界**，而真实串口没有。只在 simulator 模式下验证过的接收代码，
隐含地依赖了这个性质（见 [`verification.md`](verification.md#真实缺陷)）。
管道一端的 `receive()` 返回已到达的全部字节，不管分几次写入——粘包、半包都会真实出现。

## 数据怎么流动

### 上行：一条读数

```
STM32 ──字节──► SerialChannel.receive()
                    │
                    ▼
            FrameStreamBuffer        拼帧：粘包切开、半包等待、脏字节重同步
                    │
                    ▼
            protocol.decode()        帧头、长度、CRC-32；失败则整帧丢弃
                    │
                    ▼
         HardwareDeviceReceiver      按设备号过滤，JSON 载荷 → DataPoint
                    │                （可选地向 LinkMonitor 报告每一帧与每一次异常）
                    ▼
          DataService.publish()      ← simulator 模式也从这里进来
            │      │      │     │
            ▼      ▼      ▼     ▼
          报警与  通风   历史   api 订阅者 ──► ui / gateway ──► Android、浏览器
          统计    决策   记录
```

### 下行：从决策到设备

通风决策、报警播报、LCD 上的报警位图、问答结果都要变成发给设备的命令。
它们都遵守同一个模式：**回调里只记录，轮询循环里才发送。**

```python
fan.handle_decision(decision)   # 在 DataService 回调里：只记下期望状态
...
runner.run_once()               # 轮询循环：读串口、发布读数
fan.dispatch_pending()          # 紧接着：此时才真正下发命令
```

这不是风格偏好。回调是在接收循环读串口的过程中被触发的，如果在回调里直接发送命令，
就会**重入**设备管理器——它要在同一个串口上等设备的应答帧，于是两个读者抢同一条字节流、
互相吃掉对方的帧。第一版就是这么写的，结果是测试进程直接崩溃；在真机上则会在等应答期间冻结界面、丢读数。

几个派发器各自的细节不同：风扇命令携带的是**状态**（与上次已下发的值去重，失败下轮自动重试）；
报警播报是**事件**（不去重，发出后失败也不重试——迟到的播报比不播更糟）；
有人手动占用设备时自动派发让位。

### 多个呈现端

```
                 ┌─► ui（PyQt6 桌面端）
api.ApiInterface ┤
                 └─► gateway ─┬─► REST：设备、命令、历史、通风、问答、链路统计
                              └─► WebSocket：读数、统计、报警状态、通风决策、问答补送、链路事件
                                        │
                                        ├─► Android 客户端
                                        └─► web/ 浏览器控制台

application ─► 板载 LCD（经串口命令：报警位图、问答结果页）
```

网关的 WebSocket 由 `EventHub` 把同步回调桥接到 asyncio：每个客户端一条有界队列，
消费慢的客户端只丢**自己**最旧的消息，不会拖慢数据管线，丢弃数经 `/health` 可见。

问答的回答分两段：REST 立刻返回模板答案（毫秒级），模型改写好之后（数秒）再经 WebSocket 补送。
这样没接模型的部署不会变慢，只调 REST 的客户端也总能拿到正确答案。

## 扩展点

| 要加 | 改哪里 |
| --- | --- |
| 一种通信方式（TCP、蓝牙） | `communication/` 下新增一个 `CommunicationChannel` 实现，组合代码里换上它 |
| 一种设备 | `device/` 下实现 `DeviceInterface`；有阈值的话在 `service/sensor_data_processor.py` 登记规则 |
| 一个呈现端 | 与 `ui`、`gateway` 平级的新包，只消费 `api`；或者做成网关的又一个客户端（如 `web/`） |
| 一类问答 | `service/assistant/` 里加一种意图，补上取数与措辞，管线不变 |
| 一条设备需要解释的命令 | 在两端固定编码，见 [`protocol.md`](protocol.md#命令码) |
