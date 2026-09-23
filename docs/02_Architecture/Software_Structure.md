# 工程目录结构设计

## 设计原则

- **模块化**：每个功能领域独立成模块，避免跨模块的隐式依赖
- **分层对应**：目录结构应直接反映 `System_Architecture.md` 中定义的五层架构
- **可维护性**：单个文件不承担过多职责，禁止"大杂烩"式文件
- **可扩展性**：新增设备类型、通信方式、协议版本时，只需新增文件/子模块，不修改已有结构

> 本文档仅定义推荐的目录结构与各目录职责，不包含具体代码或文件内容。

> **阅读提示（2026-09-07 补充）**：下方"推荐目录结构"与"模块职责说明"两节是**编码开始之前**的初期设计参考，其中若干目录（`src/common/`、`src/ui/views/`、`src/protocol/frame/`、`resources/` 等）在实际编码中并未按该形态落地。**当前仓库的真实结构以本文档末尾新增的"实际落地结构（编码阶段实况）"一节为准**；本节保留不删，用于追溯设计意图的演化过程。

## 推荐目录结构

```
project_root/
├── CLAUDE.md                      # Claude Code 开发最高优先级约束文件
├── docs/                          # 文档体系（当前文档所在目录）
│
├── src/                           # 源代码根目录（后续开发阶段使用）
│   ├── ui/                        # UI Layer：界面、交互、可视化组件
│   │   ├── views/                 # 各功能页面/窗口
│   │   ├── widgets/                # 可复用界面控件
│   │   └── resources/              # 界面相关静态资源
│   │
│   ├── application/                # Application Layer：业务逻辑
│   │   ├── device_manager/         # 设备生命周期管理
│   │   ├── data_processing/        # 数据处理与转换
│   │   └── task_scheduler/         # 任务/指令调度
│   │
│   ├── protocol/                   # Protocol Layer：协议编解码
│   │   ├── frame/                  # 帧结构定义与编解码
│   │   ├── codec/                  # 具体命令的编解码实现
│   │   └── validators/             # 校验（如 CRC）相关逻辑
│   │
│   ├── communication/               # Communication Layer：通信介质收发
│   │   ├── uart/
│   │   ├── usb/
│   │   ├── tcpip/
│   │   └── bluetooth/
│   │
│   └── common/                     # 跨层共享的通用能力
│       ├── logging/                 # 日志
│       ├── config/                  # 配置管理
│       └── exceptions/              # 统一异常定义
│
├── tests/                          # 测试代码（与 src 结构对应）
│   ├── test_ui/
│   ├── test_application/
│   ├── test_protocol/
│   └── test_communication/
│
└── resources/                      # 项目级资源（非代码）
    ├── device_profiles/             # 设备描述/配置文件
    └── protocol_specs/               # 协议规范文档的机器可读版本（如有）
```

## 模块职责说明

| 目录 | 对应架构层 | 职责 |
| --- | --- | --- |
| `src/ui/` | UI Layer | 界面展示与用户交互，不含通信/协议逻辑 |
| `src/application/` | Application Layer | 业务流程编排，连接 UI 与底层通信 |
| `src/protocol/` | Protocol Layer | 帧封装/解析、校验，与通信介质无关 |
| `src/communication/` | Communication Layer | 各类通信介质的连接管理与字节收发 |
| `src/common/` | 跨层支撑 | 日志、配置、异常等基础设施，供各层调用 |
| `tests/` | 对应各层 | 单元测试与集成测试，结构与 `src/` 保持一致 |

## 扩展性说明

- 新增设备类型：在 `resources/device_profiles/` 中新增设备描述文件，并在 `src/protocol/codec/` 中新增对应编解码实现，无需改动其他层。
- 新增通信方式：在 `src/communication/` 下新增子模块，实现统一的通信接口即可接入。
- 新增协议版本：在 `src/protocol/` 内以版本或设备类型区分子模块，避免修改已有协议实现。

本结构为**初期设计参考**，具体细化将在毕设方向确定、进入实际编码阶段后，根据 `04_Development/Development_Rules.md` 中的约束进一步完善。

---

## 实际落地结构（编码阶段实况）

> 本节补充于 2026-09-07，记录**当前仓库的真实结构**，取代上文"推荐目录结构"作为工程结构的事实依据。
> 补充原因：`src/gateway/` 自 2026-08-15 起已实现并投入使用，但 `docs/02_Architecture/` 下的四份架构文档
> 均未记载它，形成"有实现、无架构文档"的缺口（违反 `CLAUDE.md`"没有文档说明的功能不视为开发完成"）。
> 本节不改变任何既有的分层决策与职责边界，只是把已经发生的落地形态如实记录下来。

### 顶层目录

```
project_root/
├── CLAUDE.md               Claude Code 开发最高优先级约束文件
├── pyproject.toml          Python 工程配置（依赖、ruff、mypy、pytest）
├── *.bat                   五个 Windows 一键启动器（见 05_Test/Runtime_Mode.md）
├── docs/                   文档体系（01~10 号目录）
├── src/                    Python 上位机源码（10 个包，见下）
├── scripts/                启动入口与验证工具（组合根，非示例代码）
├── tests/                  测试代码，结构与 src/ 一一对应，另加 integration/ 与 scripts/
├── firmware/stm32f407/     STM32F407 固件（Keil MDK 工程，独立工具链，不共用构建/测试流程）
├── android/                Android 客户端（Kotlin + Gradle 工程，独立工具链）
└── web/                    Web 控制台（原生 JS，网关的客户端，2026-09-23 设立，见 Web_Console_Design.md）
```

### `src/` 下的 10 个包

概念上仍是 `System_Architecture.md` 定义的五层架构；代码上把其中的支撑与桥接职责细分为 `core`、`service`、`api` 三个包，在多端接入后增加了与 `ui` 平级的 `gateway`，并在 2026-09-08 加入环境问答助手时增加了 `llm`。

| 包 | 对应架构层 | 职责 |
| --- | --- | --- |
> **顶级目录（不属于 `src/`，各自独立的工具链）**：`firmware/stm32f407/`（Keil MDK + HAL）、
> `android/`（Gradle + Kotlin）、`training/`（本地模型训练，2026-09-18 设立）、`web/`（Web 控制台，2026-09-23 设立）。
> 四者都不进 `pytest` 与 `mypy src` 的范围，依赖也不写进 `pyproject.toml`；
> **`src/` 与它们互不 import**。训练与平台的交接面是 Ollama 的模型名，不是 Python 符号，
> 因此训练怎么改动都伤不到已稳定的运行期代码。约定见 `training/README.md`。

| `src/core/` | 跨层支撑 | 共享基础类型（id 别名）、通用异常基类、时间戳工具；另有 `channel_display.py`（2026-09-18 新增：通道中文名／单位／小数位，`ui`、`gateway`、归档导出三处共用的唯一定义。**仍只是展示约定**，`protocol`/`communication` 不得据此判断；放这里是因为呈现端不止一个，而 `import ui.*` 会连带拉进 PyQt6）。被所有层依赖，不依赖任何人 |
| `src/device/` | Hardware Device Layer 的软件抽象 | `DeviceInterface` 抽象、`SimulatorDevice`/`RemoteDevice`、能力描述、`sensors/` 传感器模拟器 |
| `src/protocol/` | Protocol Layer | 帧结构定义与编解码、CRC-32 校验，与通信介质无关 |
| `src/communication/` | Communication Layer | 统一字节收发契约 `CommunicationChannel` 及其实现（`LoopbackChannel`/`SerialChannel`） |
| `src/service/` | Service Layer（原五层中 Application 的细分） | 数据/指令模型、数据分发、控制权管理、阈值报警与统计处理 |
| `src/application/` | Application Layer | 组合根与运行时：`ApplicationRuntime`、`DeviceManager`、帧流拼接、两种模式的接收循环与 Runner |
| `src/api/` | 桥接层（原五层中 UI 与 Application 之间的细分） | `ApiInterface` 统一入口 + `LocalApi` 本地直连实现，是所有呈现端唯一允许调用的门面 |
| `src/ui/` | Presentation Layer · PC 端 | PyQt6 界面（MVC：`controller.py` + `main_window.py` + `widgets/`） |
| `src/gateway/` | Presentation Layer · 网络端 | **PC 内置网关**：REST + WebSocket，把 `ApiInterface` 表达为网络接口，供 Android 客户端消费 |
| `src/llm/` | 外部模型服务接入层 | 本地语言模型服务的适配器（`OllamaClient`，非阻塞）。与 `communication/` 平级但不同——后者接**设备**、向上给 `protocol` 字节流；本包接模型服务、向上给 `service.assistant` 文本。只依赖标准库，**不 import `service`** |
| `src/storage/` | 本地持久化接入层 | 历史读数的存储适配器（`SqliteHistoryStore`，标准库 `sqlite3`）。与 `communication/`、`llm/` 三者同为"接外部资源"的顶层适配包，只是接的资源分别是设备、模型服务与磁盘。**不 import `service` 的实现**，`HistoryStore` 协议定义在消费方 `service/history.py` |

每个包目录下均有 `README.md` 说明其职责边界与依赖关系。

> **2026-09-17 结构变更已落地**：`src/storage/` 为本地历史记录新增（方案 A），动机、影响范围与
> 替代方案取舍（为什么不放进 `application/` 或 `service/`）见
> [`History_And_Cloud_Design.md`](History_And_Cloud_Design.md) 第 3.2 节。
> 顶层包由十个变为十一个。
>
> **2026-09-08 结构变更已落地**：`src/llm/` 为环境问答助手新增，动机、影响范围与替代方案取舍
> （为什么不并入 `communication/` 或 `application/`）见 [`Assistant_Design.md`](Assistant_Design.md) 第 4.1 节。
> 同期在 `src/service/` 下新增子包 `service/assistant/`（问答管线：意图 / 取数 / 措辞 + `LlmClient` 端口），
> 属于既有包内的细分，不改变分层。

### 依赖方向

```
  ui      ──►  api  ──►  application  ──►  service
                              │               │
  gateway ──►  api            ├──► protocol ──┘
                              ├──► communication
                              ├──► device
                              └──► llm        （只在此处被创建/装配）
  core                                （被所有层依赖，不依赖任何人）
```

`llm` 的位置与 `communication` 完全对称：**具体对象只能在 `application`/`scripts` 中被创建**，
上游（`service.assistant`）只认自己定义的 `LlmClient` 协议，不 import `llm`。

`ui` 与 `gateway` 是**两个平级的呈现端**：都只消费 `api.ApiInterface`，谁也不 import 谁。这一对等关系是 `Multi_Client_System_Architecture.md` 第 4 节"Presentation Layer 按客户端平台分别实现，但都通过统一的概念接口"在代码上的直接落点，详见该文档第 2.3 节与 `src/gateway/README.md`。

三条被写进自动化测试的硬边界（同 `CLAUDE.md`"架构原则"）：

- `src/ui/*` 只能 import `src/api`（且只经由 `ui/controller.py`），不得 import `device`/`communication`/`protocol`/`application`/`service` 的实现类
- `src/api/*` 只依赖 `application` 与 `core`/`service` 的共享数据模型，不得被 `service`/`application` 反向依赖
- 具体通信介质相关的对象（`SerialChannel`/`HardwareDeviceReceiver`/`HardwareRuntimeRunner`/`RemoteDevice` 等）只允许在 `src/application/*` 或 `scripts/` 的组合脚本中创建与装配，**禁止出现在 `src/ui/*` 与 `src/gateway/*` 里**

### 与"推荐目录结构"的主要差异

| 初期设想 | 实际落地 | 原因 |
| --- | --- | --- |
| `src/common/`（logging/config/exceptions） | `src/core/` | 命名统一为 `core`；配置与日志尚未形成独立子模块，未预先建空目录 |
| `src/ui/views/`、`src/ui/resources/` | 仅 `src/ui/widgets/` + `theme.py` | 单窗口应用无需 views 分层；样式集中在 `theme.py`，未产生独立资源目录 |
| `src/protocol/{frame,codec,validators}/` | `src/protocol/` 下四个平铺文件 | 当前只有一个协议版本，拆子目录属于过早分层 |
| `src/communication/{uart,usb,tcpip,bluetooth}/` | `src/communication/` 下平铺 `loopback.py`/`serial.py` | 只实现了实际用到的两种介质，其余按需新增文件即可 |
| `src/application/{device_manager,data_processing,task_scheduler}/` | 拆为 `application/` + `service/` 两个包 | 见 `Core_Service_Design.md`：Service Layer 被独立出来承担数据/指令模型与分发 |
| 无 | **`src/api/`** | 呈现端需要一个统一门面，见 `Core_Service_Design.md` 第 8 节 |
| 无 | **`src/gateway/`** | 多端接入后新增的网络呈现端，见 `Multi_Client_System_Architecture.md` 第 2.3 节 |
| 无 | **`src/llm/`** | 环境问答助手接入本地语言模型所需的适配层，见 `Assistant_Design.md` 第 4.1 节 |
| 无 | **`src/storage/`** | 本地历史记录所需的持久化适配层，见 `History_And_Cloud_Design.md` 第 3.2 节 |
| `resources/`（device_profiles/protocol_specs） | 未建立 | 设备能力当前由代码中的 `DeviceCapability` 描述，尚无外部配置文件需求 |

### 扩展性（对应上文"扩展性说明"的实际形态）

- **新增设备类型**：在 `src/device/` 下新增实现 `DeviceInterface` 的类；若为传感器，在 `device/sensors/` 下新增模块并在 `service/sensor_data_processor.py` 中登记阈值规则
- **新增通信方式**：在 `src/communication/` 下新增实现 `CommunicationChannel` 的模块，其余各层不受影响
- **新增呈现端**：新增一个与 `ui`/`gateway` 平级的包，只消费 `api.ApiInterface`
- **新增问答能力**：在 `service/assistant/models.py` 的 `IntentKind` 中增加一种意图，并在 `retrieval.py`/`phrasing.py` 中补上取数与措辞——三层管线不变，也不需要新的包（未来的列车时刻表查询即按此扩展，见 `Assistant_Design.md` 第 3 节）
- **新增启动组合**：在 `scripts/` 下新增组合脚本，不得让 `ui`/`gateway` 感知底层通信方式
