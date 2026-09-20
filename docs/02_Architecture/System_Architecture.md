# 系统架构设计

## 概述

本平台采用**自上而下的分层架构**，将系统划分为五层，各层之间通过明确定义的接口通信，禁止跨层直接调用（例如 UI 层不得直接操作串口）。这种设计是为了保证通信方式、设备协议、硬件类型的变化不会波及上层业务逻辑与界面。

```
┌─────────────────────────────┐
│          UI Layer            │  用户界面、交互、可视化
├─────────────────────────────┤
│      Application Layer       │  业务逻辑、设备管理、数据处理
├─────────────────────────────┤
│       Protocol Layer         │  帧编解码、校验、协议解析
├─────────────────────────────┤
│     Communication Layer      │  UART / USB / TCP/IP / 蓝牙 收发
├─────────────────────────────┤
│     Hardware Device Layer    │  实际嵌入式设备（STM32/MSPM0/ESP32 等）
└─────────────────────────────┘
```

## 各层职责

### UI Layer（界面层）

- 负责用户交互：设备连接操作、参数配置、数据展示
- 仅通过 Application Layer 提供的接口获取数据和发送指令
- 不包含任何通信逻辑或协议解析逻辑
- 可根据不同应用场景（调试工具、监控面板等）替换或扩展界面实现

> **多端展开（2026-09-07 补记）**：本层在多端场景下演化为 **Presentation Layer**，可存在多个**平级**实现，它们都只通过统一门面（代码上为 `api.ApiInterface`）取数与下发指令，互不依赖。当前已落地两个：`src/ui/`（PyQt6 桌面界面）与 `src/gateway/`（REST + WebSocket 网关，供 Android 客户端消费）。本层的职责定义不因此改变——"不包含任何通信逻辑或协议解析逻辑"同样约束 `gateway`。详见 `Multi_Client_System_Architecture.md` 第 2.3、4 节与 `Software_Structure.md`"实际落地结构"一节。

### Application Layer（应用层）

- 承载核心业务逻辑：设备生命周期管理、数据处理与转换、任务调度
- 对上（UI Layer）提供统一的数据/操作接口
- 对下（Protocol Layer）调用协议层完成指令封装与数据解析
- 是连接"用户意图"与"设备通信"的中枢

> **旁挂的适配层（2026-09-17 补记）**：本层之外另有两个**不接设备**的适配层，
> 它们与 Communication Layer 平级但方向不同——一个接本地语言模型（`src/llm/`，2026-09-08 新增），
> 一个接磁盘（`src/storage/`，2026-09-17 新增，SQLite 历史库、归档台账与 OSS 上传器）。
> 五层模型不因此改变：**两者都只能由 Application Layer 或 `scripts/` 创建**，
> 且**不得被 Service 层 import**——所需协议（`LlmClient`、`HistoryStore`）定义在消费方，
> 依赖方向因此仍然朝下。理由与落地结构见 `Software_Structure.md`"实际落地结构"一节、
> `Assistant_Design.md` 第 4.1 节与 `History_And_Cloud_Design.md` 第 3.2 节。

### Protocol Layer（协议层）

- 定义与实现通用通信协议的编解码规则（详见 `03_Communication/Protocol_Design.md`）
- 负责帧的封装、解析、校验（如 CRC）
- 与具体通信介质无关，只处理"字节流 ↔ 结构化数据"的转换
- 可根据设备类型扩展不同的协议实现，但对上层暴露统一接口

### Communication Layer（通信层）

- 负责与具体通信介质的数据收发：UART、USB、TCP/IP、蓝牙
- 管理连接状态（打开、关闭、超时、重连）
- 向 Protocol Layer 提供统一的字节流读写接口，屏蔽底层通信方式差异
- 不解析数据内容，只负责可靠的字节传输

### Hardware Device Layer（硬件设备层）

- 实际的嵌入式设备本体（STM32、MSPM0、ESP32 等）
- 不属于上位机软件的一部分，但其通信协议与接口特性会影响 Protocol Layer 和 Communication Layer 的设计
- 平台需保证在设备型号变化时，仅需调整对应的协议实现，而非整体架构

## 数据流向

**下行（指令下发）：**

```
UI Layer → Application Layer → Protocol Layer（封装帧）→ Communication Layer（发送字节流）→ Hardware Device
```

**上行（数据上报）：**

```
Hardware Device → Communication Layer（接收字节流）→ Protocol Layer（解析帧）→ Application Layer（业务处理）→ UI Layer（展示）
```

所有跨层数据传递均应通过明确定义的接口/数据结构进行，禁止跳层调用（如 UI 直接读写串口）。

## 为什么采用分层设计

1. **设备无关性**：不同嵌入式设备的差异应被限制在 Protocol Layer 和 Communication Layer，不应扩散到业务逻辑和界面。
2. **通信方式可替换**：从 UART 切换到 TCP/IP 或蓝牙时，只需替换 Communication Layer 的实现，上层无感知。
3. **可测试性**：各层可独立进行单元测试（例如用模拟字节流测试 Protocol Layer，无需真实硬件）。
4. **应对需求不确定性**：由于最终毕设方向尚未确定，分层架构使得平台在需求变化时只需调整局部模块，而非重构整体系统。
5. **便于团队协作与后续维护**：职责边界清晰，降低多人协作或后续接手时的理解成本。
