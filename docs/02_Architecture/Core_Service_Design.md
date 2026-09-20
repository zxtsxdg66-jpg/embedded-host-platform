# 核心服务层设计（Core Service Design）

## 文档定位

`Multi_Client_System_Architecture.md` 定义了 PC 上位机与 Android 客户端并存的多端架构，明确"Application Layer 语义统一、实现可分别落地"这一原则，但未展开"语义统一"具体指什么。本文档承接该原则，定义多客户端系统中**核心服务层（Service Layer）**的设计：即 Application Layer 内部、真正承载"设备是什么""数据长什么样""指令怎么表达"这一组公共契约的部分。

本文档是对 Application Layer 职责的**细化说明**，不新增架构层，不改变 `System_Architecture.md` 定义的五层结构，也不改变 `Software_Structure.md` 中 `src/application/` 的目录职责划分。

> 本文档仅为设计文档，不包含代码实现，不绑定具体传感器、控制对象或 MCU 型号。

## 与既有文档的一致性说明

- 分层术语与 `System_Architecture.md` 保持一致：Service Layer 是 **Application Layer** 内部的核心组成部分，位于 Protocol Layer 之上、Presentation Layer（原 UI Layer，定义见 `Multi_Client_System_Architecture.md`）之下
- 通信抽象与 `Communication_Design.md` 保持一致：Service Layer 不直接感知 UART/USB/TCP/蓝牙等具体通信介质，只通过 Protocol Layer 收发结构化帧
- 目录映射与 `Software_Structure.md` 保持一致：本文档描述的能力对应 `src/application/device_manager/`、`src/application/data_processing/`、`src/application/task_scheduler/` 三个模块的设计内容细化，不新增目录、不重命名已有模块
- 多端关系与 `Multi_Client_System_Architecture.md` 保持一致：Service Layer 是 PC 与 Android 两端 Application Layer 实现"语义统一"的具体载体

> **2026-09-14 补记（只补指引，不改本文设计）**：本文写于编码之前，第 15 行提到的三个目录名是设计期名称，仓库实际的 10 个包及其依赖方向见 `Software_Structure.md`"实际落地结构"一节。本文之后新增的两块内容在别处有完整说明：
> - **环境问答助手**（`src/service/assistant/`）与**本地语言模型适配层**（`src/llm/`）：`llm` 与 `communication` 平级，只能由 `application` 或 `scripts` 创建，不得被 `service` import；`LlmClient` 协议定义在消费方 `service/assistant/llm_port.py`（依赖倒置）。取舍见 `Assistant_Design.md` 第 4.1 节，对模型的四层约束见 `LLM_Boundary.md`
> - **四个向设备下发的派发器**（`application/` 下的 `fan_dispatcher`、`alert_dispatcher`、`alarm_state_dispatcher`、`answer_dispatcher`）：一律"回调里只记录、轮询循环里才发送"，以免重入串口。见 `src/application/README.md`

---

## 1. Device 抽象设计

### 1.1 设计目标

Device 抽象的核心目标是让 Service Layer 及以上各层（Application 的其余部分、Presentation Layer）在**不知道设备具体型号**的前提下，完成设备的发现、连接、能力查询与状态管理。

### 1.2 抽象要素

Device 抽象由以下几组信息构成，均为概念定义，不涉及具体字段类型或编码：

| 要素 | 说明 |
| --- | --- |
| **设备标识（Device Identity）** | 对应 `Protocol_Design.md` 中的"设备ID"字段，是设备在系统内的唯一标识，与设备的物理型号、通信方式无关 |
| **设备能力描述（Device Capability Descriptor）** | 描述该设备支持哪些命令类型、能上报哪些数据通道，由设备侧协议实现方在接入时提供或由上位机侧配置文件描述（详见 `Software_Structure.md` 中 `resources/device_profiles/` 的用途），不在架构层面预设具体能力清单 |
| **连接状态（Connection State）** | 描述设备当前是否可达、正在连接中、已断开、异常等状态，来源于 Communication Layer 的状态回调（见 `Communication_Design.md` "状态可观测"原则），经 Service Layer 汇总后对外暴露 |
| **占用状态（Occupancy State）** | 多客户端场景下，描述设备当前的访问关系（空闲 / 被独占 / 被只读共享），用于支撑第 7 节的多客户端访问规则 |
| **设备元信息（Device Metadata）** | 可选的描述性信息（如设备名称、接入时间、所属通信方式），不影响协议解析，仅用于展示与管理 |

### 1.3 设计原则

1. **能力描述与设备型号解耦**：系统不区分"这是一个 STM32"还是"这是一个 ESP32"，只区分"这个设备支持哪些命令类型和数据通道"。型号信息仅作为元信息存在，不参与业务逻辑判断。
2. **Device 抽象是 Protocol Layer 之上的产物**：Device 对象由 Service Layer 在建立连接、完成能力协商后构建，Protocol Layer 本身不持有 Device 概念，只处理帧的编解码。
3. **一个 Device 抽象对应一个协议意义上的设备实例**：与之建立的物理连接（UART/TCP/BLE 等）可以更换，只要设备标识和能力描述保持一致，Device 抽象在系统中的身份不变。

---

## 2. 数据模型设计

### 2.1 分层中的数据形态演化

数据在系统中从设备到界面，经历三种形态，Service Layer 负责承上启下的第二种到第三种的转换：

```
原始字节流（Communication Layer）
      │
      ▼
结构化帧（Protocol Layer：帧头/设备ID/命令类型/数据长度/Payload/CRC）
      │
      ▼
业务数据模型（Service Layer：与具体协议字段解耦的通用数据结构）
      │
      ▼
展示数据（Presentation Layer：图表、数值面板等 UI 呈现形式）
```

### 2.2 通用数据模型要素

Service Layer 对外暴露的数据模型不绑定具体传感器或物理量，由以下通用要素构成：

| 要素 | 说明 |
| --- | --- |
| **来源设备（Source Device）** | 关联第 1 节定义的 Device 标识 |
| **数据通道（Channel）** | 标识这条数据属于设备的哪一类上报内容（如"通道 1""状态字段 A"），通道的具体业务含义由设备能力描述定义，Service Layer 不假设通道内容 |
| **数值内容（Value）** | 通用的数值/结构化载荷，具体类型（标量、数组、枚举状态等）由通道定义决定，Service Layer 不限定为单一数值类型 |
| **时间戳（Timestamp）** | 数据产生或接收的时间，用于时序展示、历史记录与回放（呼应 `Project_Overview.md` 中"数据记录与回放"的规划功能） |
| **有效性标记（Validity）** | 标记该数据是否通过协议校验、是否在合理范围内，供上层决定是否展示或丢弃，不在 Service Layer 内做业务含义上的"合理性"判断（该判断属于未来具体应用场景的职责，不在通用平台架构中预设） |

### 2.3 设计原则

1. **业务数据模型与协议帧结构解耦**：Protocol Layer 的 Payload 格式变化（如新增命令类型）不应导致 Service Layer 对外的数据模型结构发生破坏性变化，两者之间通过转换逻辑衔接。
2. **不预设物理量语义**：数据模型中不出现"温度""电压""转速"等具体业务词汇，这类语义由设备能力描述或更上层的应用配置赋予，保证平台面向不同毕设方向的通用性。
3. **面向订阅而非轮询**：数据模型的产生方式应支持"上层订阅数据通道，Service Layer 在新数据到达时主动通知"，而非要求上层持续轮询查询，以匹配 `Communication_Design.md` 中"异步非阻塞"的通信原则。

---

## 3. 控制指令模型设计

### 3.1 指令模型要素

指令模型描述客户端如何向设备表达"意图"，与第 2 节的数据模型相对，是下行方向的通用契约：

| 要素 | 说明 |
| --- | --- |
| **目标设备（Target Device）** | 关联第 1 节定义的 Device 标识 |
| **指令类型（Command Type）** | 对应 `Protocol_Design.md` 中的"命令类型"字段，标识意图种类（如"读取状态""下发配置"），具体命令类型集合由设备能力描述给出 |
| **指令参数（Parameters）** | 通用的参数载荷，结构由指令类型决定，Service Layer 不限定参数的具体业务含义 |
| **指令来源（Origin）** | 标识该指令由哪个客户端（PC 或 Android）、哪次会话发起，用于第 7 节的多客户端仲裁与操作留痕 |
| **指令时间戳（Issued At）** | 指令发起时间，用于超时判断与顺序追溯 |
| **执行结果（Result）** | 指令的最终状态，包括"待确认""成功""失败""超时"等，供发起方客户端感知 |

### 3.2 指令生命周期

```
客户端发起指令
      │
      ▼
Service Layer 接收并生成指令记录（状态：待确认）
      │
      ▼
Protocol Layer 编码为帧 → Communication Layer 发送
      │
      ▼
（等待设备响应，或超时）
      │
      ├─ 收到确认帧 ──> Service Layer 更新指令状态（成功/失败，依据设备返回内容）
      └─ 超时未响应 ──> Service Layer 更新指令状态（超时）
      │
      ▼
指令结果回传给发起方客户端（其他客户端可选择是否感知该指令，见第 7 节）
```

### 3.3 设计原则

1. **指令与数据在模型上对称但方向相反**：数据模型描述"设备说了什么"，指令模型描述"客户端要设备做什么"，两者共享"设备标识 + 时间戳"的基础结构，便于统一处理和记录。
2. **指令必须可追溯来源**：多客户端场景下，任何下发到设备的指令都必须能够回答"是谁在什么时候发的"，这是第 7 节仲裁规则得以设计的前提。
3. **不预设指令的业务后果**：Service Layer 只负责指令的表达、发送与结果跟踪，不对指令的业务合理性做判断（如是否会导致设备进入危险状态），此类判断属于具体应用场景的职责，不在通用平台架构中预设。

---

## 4. Service Layer 职责

### 4.1 职责范围

Service Layer 是 Application Layer（`src/application/`）内部承上启下的核心部分，具体职责包括：

- **设备生命周期管理**：设备的发现、连接建立与断开、能力协商、Device 抽象对象的创建与销毁（对应 `src/application/device_manager/`）
- **数据处理与分发**：将 Protocol Layer 解析出的结构化帧转换为第 2 节定义的通用数据模型，并按订阅关系分发给上层（对应 `src/application/data_processing/`）
- **指令调度与跟踪**：接收上层发起的指令请求，转换为第 3 节定义的指令模型，交由 Protocol Layer 编码发送，并跟踪指令生命周期（对应 `src/application/task_scheduler/`）
- **多客户端会话与访问控制**：维护当前有哪些客户端在访问哪些设备，执行第 7 节定义的访问规则

### 4.2 职责边界（不做什么）

- **不做协议帧的编解码**：这是 Protocol Layer 的职责，Service Layer 只使用 Protocol Layer 暴露的"结构化帧收发"接口
- **不做物理连接的建立与维护**：这是 Communication Layer 的职责，Service Layer 通过 Protocol Layer 间接依赖 Communication Layer，不直接调用串口/网络 API
- **不做界面渲染或交互逻辑**：这是 Presentation Layer 的职责，Service Layer 只提供数据订阅与指令发起的接口，不关心数据最终以图表还是数值面板呈现
- **不预设具体业务规则**：如"某类数据超过阈值应如何处理"，属于具体应用场景（未来毕设方向明确后）的职责，通用平台的 Service Layer 只提供数据和指令的通道能力

### 4.3 在直连模式与网关模式下的形态差异

呼应 `Multi_Client_System_Architecture.md` 第 2.2 节定义的两种接入模式：

- **直连模式（Direct Mode）**：Service Layer 作为客户端 Application Layer 的一部分，与该客户端的 Protocol/Communication Layer 一同运行在同一进程内（PC 或 Android 各自拥有一份）
- **网关模式（Gateway Mode，预留）**：Service Layer 的设备管理、数据分发能力可以集中运行在网关服务中，PC 与 Android 客户端的 Application Layer 退化为"Service Layer 的远程调用方"，具体调用关系见第 5 节

两种模式下 Service Layer 对外暴露的概念模型（Device 抽象、数据模型、指令模型）保持一致，变化的只是它的"部署位置"，这也是 `Multi_Client_System_Architecture.md` 中"语义统一、实现可分别落地"原则在 Service Layer 层面的具体体现。

---

## 5. PC 端和 Android 端调用关系

### 5.1 直连模式下的调用关系

```
PC 端：
  PC Presentation Layer（PyQt6）
        │  （调用 Service Layer 提供的接口：订阅数据 / 发起指令 / 查询设备）
        ▼
  PC 端 Service Layer（本地，运行于同一进程）
        │
        ▼
  PC 端 Protocol Layer → PC 端 Communication Layer → 设备

Android 端：
  Android Presentation Layer
        │  （调用 Service Layer 提供的接口，概念上与 PC 端一致）
        ▼
  Android 端 Service Layer（本地，运行于同一进程）
        │
        ▼
  Android 端 Protocol Layer → Android 端 Communication Layer → 设备
```

两端的 Presentation Layer 面对的是**同一套概念接口**（设备查询、数据订阅、指令发起、结果回调），只是接口的具体实现语言、调用方式（同步/异步、回调/协程等）随平台技术栈不同而不同，这属于工程实现细节，不属于架构分裂。

### 5.2 网关模式下的调用关系（预留）

```
PC Presentation Layer ──┐
                        ├──(网络调用，如 TCP/WebSocket)──> 网关中的 Service Layer ──> Protocol Layer → Communication Layer → 设备
Android Presentation Layer ──┘
```

- PC 与 Android 端各自保留一个**轻量 Application Layer**，其职责从"完整实现 Service Layer"退化为"将 Presentation Layer 的调用转发给远程网关，并将网关返回的数据/结果转换为本地可用的形式"
- 对 Presentation Layer 而言，调用方式不因是否使用网关而改变——它始终面对同一套 Device 抽象、数据模型、指令模型，网关的引入只影响 Application Layer 内部"是本地实现还是远程代理"这一实现细节

#### 5.2.1 实际落地形态（2026-08-15 完成，2026-09-07 补记）

网关模式已经实现，落点为 `src/gateway/`（见 `Multi_Client_System_Architecture.md` 第 2.3、2.3.1 节）。**实际形态与上文预留模型有一处差异，在此如实记录**：

```
PC Presentation（src/ui/，PyQt6） ──────────► api.ApiInterface（进程内直接调用，无网络开销）
                                                  ▲
                                                  │ 同一个 LocalApi 实例
Android Presentation（android/） ──(REST/WS)──► src/gateway/ ──┘
```

| 上文预留模型 | 实际落地 | 差异原因 |
| --- | --- | --- |
| PC 与 Android 端**各自**保留一个轻量 Application Layer，向远程网关转发 | PC 端 `src/ui/` **不经网络**，仍在同一进程内直接调用 `api.ApiInterface`；只有 Android 端走网络 | 网关由 PC 上位机进程自己兼任，PC 侧本来就持有本地实现，没有必要为自己再包一层远程代理 |
| Android 侧有一个"把 Presentation 调用转发给远程网关"的轻量 Application Layer | Android 侧对应的是 `android/app/src/main/java/com/example/envmonitor/data/`（`GatewayClient` REST + `GatewayWebSocket` + `MessageParser`） | 职责等价——它就是那个"远程代理"，只是不叫 Application Layer；概念模型（device_id/channel/value/status 等字段）与 PC 侧完全一致，符合上文第二条原则 |

**上文第二条原则已被实现验证**：接入 Android 时 `api`/`service`/`application`/`protocol`/`communication`/`device` 六层零改动，Presentation Layer 面对的概念模型未变，变的只是"谁来把它翻译成什么形式"。

### 5.3 设计原则

1. **调用关系对客户端类型透明**：PC 与 Android 端的 Presentation Layer 不需要因为对方的存在或缺席而改变自己的调用方式
2. **本地与远程调用形态可切换，接口概念不可切换**：无论 Service Layer 运行在本地进程还是远程网关，其对外的 Device/数据/指令模型必须保持一致，这是多端协同得以实现的前提
3. **当前阶段以直连模式为实现基线**：网关模式下的调用关系目前仅作架构预留，具体的远程调用协议（REST/RPC/WebSocket 等）留待第 8 节讨论扩展方向时再展开，不在本文档中做具体选型

---

## 6. 设备模拟器设计

### 6.1 设计目的

设备模拟器（Device Simulator）用于在**没有真实 MCU 设备**的情况下，验证 Service Layer、Protocol Layer 乃至 Presentation Layer 的功能是否正确，服务于 `Development_Rules.md` 中"保留测试接口"的约束，以及 `Test_Plan.md` 中"通信测试""协议测试"不依赖真实硬件的原则。

### 6.2 模拟器在架构中的位置

模拟器不是一个独立的新层，而是 **Hardware Device Layer 的一种可替换实现**，同时在通信侧表现为 Communication Layer 抽象接口的一个实现：

```
（真实场景）
Communication Layer（UART 实现）──> 物理串口 ──> 真实 STM32 设备

（模拟场景）
Communication Layer（模拟器实现）──> 进程内/回环通道 ──> 设备模拟器
```

对 Protocol Layer 及以上各层而言，模拟器与真实设备在接口层面**不可区分**——上层通过同一套 Communication Layer 抽象接口（连接、发送、接收、状态回调，定义见 `Communication_Design.md`）与之交互，不需要为"是否是模拟器"编写特殊分支逻辑。

### 6.3 模拟器能力范围

| 能力 | 说明 |
| --- | --- |
| **协议帧应答** | 按 `Protocol_Design.md` 定义的帧格式，对收到的指令帧生成合法的响应帧，验证指令下发与结果回传的完整链路 |
| **数据主动上报** | 按可配置的节奏生成数据帧，模拟设备持续上报数据的行为，用于验证数据订阅与分发链路 |
| **设备能力可配置** | 可配置模拟出的设备支持哪些命令类型、数据通道，用于验证第 1 节 Device 抽象在不同能力组合下的表现，不绑定固定的设备画像 |
| **异常场景模拟** | 可模拟连接超时、CRC 校验失败、设备无响应、连接中断等异常情况，用于验证 Service Layer 与 Protocol Layer 的容错与恢复逻辑 |
| **多设备并存模拟** | 可同时模拟多个具备不同设备标识的虚拟设备，用于验证多设备管理与第 7 节的多客户端访问规则，而无需准备多台真实硬件 |

### 6.4 设计原则

1. **模拟器不模拟具体传感器的物理规律**：不在架构层面规定模拟器生成"温度曲线"或"振动波形"等具体业务数据，只提供通用的数值生成能力（如固定值、随机值、周期性变化等抽象模式），具体业务语义留给未来应用场景配置
2. **模拟器与真实设备共用同一套协议实现**：模拟器不应绕过 Protocol Layer 直接构造"假数据"塞给 Service Layer，而应像真实设备一样，经过完整的帧编解码路径，以保证测试的真实性
3. **模拟器是长期保留的开发资产**：不是临时调试脚本，而是与 `Test_Plan.md` 中的测试方案配套、长期维护的能力，PC 端与 Android 端均可复用同一套模拟器（或其在各自技术栈下的等价实现）进行开发期联调

---

## 7. 多客户端访问规则

### 7.1 访问关系分类

呼应 `Multi_Client_System_Architecture.md` 第 5.2 节提出的"数据分发"与"指令仲裁"问题，本节给出 Service Layer 层面的基线规则：

| 访问类型 | 默认规则 |
| --- | --- |
| **数据订阅（只读）** | 允许多个客户端同时订阅同一设备的数据，Service Layer（或网关模式下的集中 Service Layer）以第 5.2 节描述的"一对多分发"方式向所有订阅方推送相同数据，不做互斥限制 |
| **指令下发（读写）** | 默认采用**独占会话**规则：同一设备在同一时刻只接受一个客户端的指令下发权限，其他客户端可查看设备状态与数据，但指令请求会被拒绝或排队，直到当前持有方释放 |
| **设备连接持有** | 直连模式下，物理连接由建立连接的客户端持有，其占用状态需通过第 1 节定义的"占用状态"对外可见；网关模式下，物理连接统一由网关持有，客户端之间天然不产生连接层面的冲突 |

### 7.2 占用状态流转

```
空闲（Free）
   │  客户端 A 请求获得指令下发权限
   ▼
被占用（Occupied by A）
   │  客户端 A 主动释放 / 会话超时 / 连接断开
   ▼
空闲（Free）
```

- 处于"被占用"状态时，其他客户端仍可进行数据订阅（只读），但发起指令会收到明确的"设备当前被占用"反馈，而不是静默失败或排队等待不确定时长
- 占用状态的具体获取/释放机制（如是否支持抢占、是否有超时自动释放）留待多设备管理需求进一步明确后细化，本文档仅确立"默认独占写、允许共享读"这一基线原则

### 7.3 设计原则

1. **读写分离是默认基线，而非最终方案**：当前采用"共享读、独占写"是为了在需求不明确阶段给出一个安全、可预期的默认行为，避免多客户端同时下发指令导致设备状态冲突；更精细的仲裁策略（如按客户端优先级、按指令类型细分权限）留待具体应用场景明确后扩展
2. **占用状态必须对所有客户端可见**：任何客户端在尝试获取指令权限前，都应能查询到设备当前的占用状态，避免"盲发指令后才发现被拒绝"的糟糕体验
3. **规则由 Service Layer 统一执行**：无论直连模式还是网关模式，占用状态的判定与指令许可逻辑都在 Service Layer 完成，Presentation Layer 不自行判断是否有权限下发指令

---

## 8. 后续 API 接口扩展方向

本文档定义的是 Service Layer 的**概念模型**，尚未涉及具体的接口协议形式（函数签名、网络 API 格式等），以下为明确技术方向后可能的扩展路径，当前不做具体选型：

1. **本地调用接口正式化**：直连模式下，PC 与 Android 端 Service Layer 对外暴露的调用接口（设备查询、数据订阅、指令发起）需要在各自技术栈中正式定义为接口/协议（Python 侧、Android 侧分别定义），保持概念一致、签名可以不同
2. **网关模式的网络 API 设计**：当第 6.3 节（`Multi_Client_System_Architecture.md`）中列出的网关引入条件成立时，需要为 Service Layer 设计对外的网络 API，候选形式包括请求-响应式（REST/RPC）用于设备查询与指令下发、长连接推送式（WebSocket）用于数据订阅，具体选型留待网关模式详细设计阶段决定
   > **已完成（2026-08-15，2026-09-07 补记）**：引入条件已于 2026-08-14 成立，候选选型已定为 **REST（查询/指令）+ WebSocket（数据/报警推送）**，实现落点 `src/gateway/`（**9 个** REST 端点 + 1 个 `/ws`；2026-08-15 落地时为 7 个，其后 09-08 加环境问答、09-17 加历史查询）。注意实际暴露网络 API 的不是 Service Layer 本身，而是其上的 `api.ApiInterface` 门面——`gateway` 是 `api` 的消费方，与 `ui` 平级，`service` 未因此增加任何对外网络职责。详见第 5.2.1 节、`Multi_Client_System_Architecture.md` 第 2.3.1 节、`src/gateway/README.md` 与 `docs/10_AndroidClient/PC_Android_接口设计.md`。
3. **指令模型的权限扩展**：在"共享读、独占写"基线规则之上，未来可扩展更细粒度的权限模型（如按指令类型区分只读/低风险/高风险操作），对应 API 层面需要携带身份与权限信息
4. **数据订阅的过滤与聚合能力**：当前数据模型按"设备 + 通道"订阅，未来可扩展为支持条件过滤（如仅订阅特定范围的数据变化）、多设备聚合订阅等能力，减少客户端侧的处理负担
5. **设备能力描述的标准化与发现协议**：当前设备能力描述被视为架构预留概念，未来可扩展为设备接入时的标准化"能力协商"过程（设备主动上报自身支持的命令类型与数据通道），减少人工维护设备配置文件的成本
6. **模拟器接口的独立暴露**：第 6 节的设备模拟器当前被视为开发测试内部工具，未来可考虑将其控制接口（如动态调整模拟数据、注入异常）也纳入 API 体系，便于自动化测试与演示场景复用

以上方向均为架构演进的可能路径，具体是否实现、以何种顺序实现，取决于后续本科毕设方向的最终确定，本文档不做强制规划。

---

## 附：与现有文档的关系

| 文档 | 关系 |
| --- | --- |
| `System_Architecture.md` | 本文档细化其 Application Layer 的内部设计，不改变五层结构定义 |
| `Multi_Client_System_Architecture.md` | 本文档是其"Application Layer 语义统一"原则的具体展开，直连/网关两种模式的定义直接沿用 |
| `Software_Structure.md` | 本文档描述的 Service Layer 能力对应 `src/application/` 下三个子模块的设计内容，不新增或重命名目录 |
| `Communication_Design.md` | 本文档中的模拟器设计与调用关系均建立在其定义的通信抽象接口与设计原则之上 |
| `Protocol_Design.md` | 本文档的 Device 抽象、数据模型、指令模型均以其定义的帧字段（设备ID、命令类型、Payload）为基础进行上层转化 |

本文档为架构设计文档，不包含实现代码，不绑定具体传感器、控制对象或 MCU 型号，未修改任何已有文档内容。
