# CLAUDE.md

本文件是 Claude Code 在本项目中进行任何开发工作时的**最高优先级约束文件**。所有代码生成、修改、重构行为均需先满足本文件中的要求；当本文件与其他文档存在冲突时，以本文件为准。

## 项目定位

- 本项目是一个**面向嵌入式设备的通用上位机开发平台**，非某一具体设备或课题的一次性工具；架构与代码设计仍需保持通用性，不得为单一假设场景硬编码——这一原则不因下面的选题收敛而改变
- 目标设备的架构层面支持范围仍是 STM32、MSPM0、ESP32 等，通信方式仍是 UART、USB、TCP/IP、蓝牙等通用能力；**本科毕设的实际验证路线已收敛**为 STM32F407ZGT6（正点原子探索者V3 开发板）+ AHT20 温湿度传感器（ATK-MB016）+ HH_07.06 噪声传感器（Modbus RTU），应用场景为地铁站公共空间环境监测。论文主线 2026-08-14 起为"通信协议设计与可靠性验证"，**2026-09-12 暂定抽象为"把不可靠的部件放在不承担正确性责任的位置"**，通信协议的可靠性保障与环境问答助手是这条原则的两个实例（助手升格为独立一章并作为核心创新点；题目是否调整待与导师确认），详见 `docs/01_Project/Project_Overview.md`"毕设应用场景与选题定位"与"论文主线的抽象"两节
- STM32 侧固件代码位于顶级目录 `firmware/stm32f407/`（Keil MDK + STM32 HAL + ARM Compiler 5.06 工程，与 `src/` 的 Python 代码是完全独立的两套工具链，不共用构建/测试流程），实施方案与进度见 `docs/09_STM32Hardware/`
- **本地模型的训练代码位于顶级目录 `training/`**（2026-09-18 设立），与 `firmware/`、`android/` 同性质：独立工具链、离线生命周期，**不进 `pytest` 与 `mypy src` 的范围**，依赖也不写进 `pyproject.toml`。**`src/` 与 `training/` 互不 import**——交接面是 Ollama 的模型名，不是 Python 符号。**尤其不得放进 `src/llm/`**：那是运行期适配层，只能由 `application`/`scripts` 创建且不得被 `service` import，与离线训练的生命周期正好矛盾。目录与产物约定见 `training/README.md`
- **Web 控制台位于顶级目录 `web/`**（2026-09-23 设立），与 `android/` 同性质：是网关（`src/gateway`）的又一个客户端，只经 REST 与 WebSocket 通信，**不 import 任何 Python 符号**，不进 `pytest` 与 `mypy src` 的范围，也不引入 npm 等前端构建链。**不得放进 `src/gateway/`**——网关是无界面服务；页面由 `scripts/` 的启动脚本按需挂载，网关包本身不知道 `web/` 的存在。**禁止让网页直连串口（Web Serial）**，那会让呈现端感知底层通信方式。设计与取舍见 `docs/02_Architecture/Web_Console_Design.md`
- 详细背景与规划见 `docs/01_Project/Project_Overview.md`
- **当前实现进度的权威快照**见 `docs/05_Test/Project_Status_Context.md`（每完成一个开发阶段应同步更新该文件，而非在本文件中堆积实现细节）；该文件 2026-09-09 已按"状态留下、过程移出"拆分，**过程记录写入 `docs/05_Test/status/` 下的分卷**，主文件只保留速查、当前状态、下一步优先级与开发约束，分卷索引在主文件顶部；两种运行模式（Simulator/Hardware）的启动方式见 `docs/05_Test/Runtime_Mode.md`；STM32 固件的实现进度见 `docs/09_STM32Hardware/STM32F407_硬件落地方案.md`

## 架构原则

- 系统概念上采用五层架构：UI Layer / Application Layer / Protocol Layer / Communication Layer / Hardware Device Layer，详见 `docs/02_Architecture/System_Architecture.md`；实际代码按 `src/core`、`src/device`、`src/protocol`、`src/communication`、`src/service`、`src/application`、`src/api`、`src/ui`、`src/gateway`、`src/llm`、`src/storage` 十一个包组织，`core`/`service`/`api` 是在原五层基础上细化出的支撑/桥接层，`src/gateway`（PC 内置 REST + WebSocket 网关，供 Android 客户端消费）与 `src/ui` 是**平级的两个呈现端**、同为 `api.ApiInterface` 的消费方，不是新增的架构层；`src/llm`（本地语言模型服务适配层，2026-09-08 新增）与 `src/communication` 平级但接的不是设备，**只能在 `src/application` 或 `scripts/` 中被创建**，且不得被 `src/service` import——`LlmClient` 协议定义在消费方 `service/assistant/llm_port.py`，理由见 `docs/02_Architecture/Assistant_Design.md` 第 4.1 节；`src/storage`（本地持久化适配层，2026-09-17 新增）与 `src/llm` 同性质、同规矩——接的是磁盘，**只能在 `src/application` 或 `scripts/` 中被创建**，且不得被 `src/service` import，`HistoryStore` 协议定义在消费方 `service/history.py`，理由见 `docs/02_Architecture/History_And_Cloud_Design.md` 第 3.2 节；具体职责与依赖方向见各包下的 `README.md`、`docs/02_Architecture/Core_Service_Design.md` 及 `docs/02_Architecture/Software_Structure.md`"实际落地结构"一节
- 各层职责边界清晰，**禁止跨层直接调用**，已在历次任务中被反复验证并写入测试：
  - `src/ui/*` 只能 import `src/api`（经 `ui/controller.py`），不得 import `device`/`communication`/`protocol`/`application`/`service`
  - `src/gateway/*` 同样只能 import `src/api`（及经 `api` 签名暴露的 `core`/`service` 共享模型类型），不得 import `device`/`communication`/`protocol`；`ui` 与 `gateway` 是架构平级模块，**两者禁止互相 import**（横向依赖），`gateway` 是无界面服务，**禁止依赖 PyQt6**
  - `src/api/*` 只能依赖 `application`（`ApplicationRuntime`）与 `core`/`service` 中的共享数据模型类型，不得反过来被 `service`/`application` 依赖
  - 具体通信介质相关的对象（`SerialChannel`/`HardwareDeviceReceiver`/`HardwareRuntimeRunner`/`RemoteDevice` 等）只能在 `src/application/*` 或 `scripts/` 组合脚本中被创建、装配，**禁止出现在 `src/ui/*` 与 `src/gateway/*` 里**——即使是"启动脚本要接入硬件模式"这类任务，也应该在 `scripts/` 里新增/扩展组合逻辑，而不是让 `ui/`、`gateway/` 感知到底层通信方式
- 工程目录结构应遵循 `docs/02_Architecture/Software_Structure.md` 中定义的模块划分
- 新增设备类型、通信方式、协议版本时，应通过扩展对应层的模块实现，而非修改整体架构
- 系统同时支持 **Simulator 模式**（`SimulatorDevice`+`LoopbackChannel`，无需硬件）与 **Hardware 模式**（`RemoteDevice`+`SerialChannel`，真实硬件），两者从 `DataService` 往上（`service`/`application` 的 `DataService` 消费方、`api`、`ui`）代码完全一致；新增功能默认应同时兼容两种模式，除非任务明确只针对其中一种。详见 `docs/05_Test/Hardware_Simulation_Mode.md`

## 代码规范

- Python 开发需遵循 `docs/04_Development/Coding_Standards.md`，包括：
  - 类型提示、异常处理、日志规范、命名规范、注释要求
- 禁止单文件堆积多个不相关职责的代码
- 禁止 UI 逻辑与通信逻辑混合
- 各层应保留可测试接口，支持在无真实硬件条件下进行验证

完整开发约束见 `docs/04_Development/Development_Rules.md`。

## 文档要求

- 任何新增或修改的功能模块，必须同步补充或更新对应设计文档
- 文档组织方式应与 `docs/` 目录体系保持一致（项目背景、架构、通信、开发规范、测试、用户手册）
- 没有文档说明的功能不视为开发完成

## Skill Usage Policy

本节基于 `docs/04_Development/Skill_Audit_Report.md` 的最终审计与精简结果，约束 Claude Code 在本项目中对 Skill 的使用方式。

### Active Development Skills

当前允许主动使用：

- `architecture`
- `uml`
- `setting-up-python-libraries`
- `improving-python-code-quality`
- `testing-python-libraries`
- `pyqt6-ui-development-rules`

这些 skill 用于：
- Python 工程规范
- PyQt6 桌面应用开发
- 软件设计建模

### Archived Skills

以下 skill 默认不要主动调用：

- `graphviz`
- `network`
- `iot`
- `data-analytics`
- `autonomous-paper-xts-main`（2026-09-08 归档）

以上均位于 `.claude/archive_skills/`，不在 `.claude/skills/` 下，不会被自动发现。

使用规则：

- 除非用户明确要求，否则不要加载 archive skill。
- 避免引入云端 IoT、大数据分析、企业网络架构等无关技术方向。
- **`autonomous-paper-xts-main` 归档原因**：它是"给定主题 → 自动检索文献 → 并行写作 → 产出约 1.2 万字论文"的全自动流水线，与本项目的处境正好相反——本项目已有约 4.8 万字、基于真实实测数据的论文，需要做的是**压缩并补入扩展功能**，而不是重新生成（篇幅口径几经调整：2 万 → 2.9 万 → 2026-09-12 起正文约 1.3 万字、六章，现行计划见 `docs/07_Thesis/论文改写方案_1.3万字.md`）。启动它等于用检索来的综述替换掉四周积累的实测记录（3489 帧零丢帧、八个真实 bug、硬件到货时 `src/` 零改动等）。其 `references/` 下的 GB/T 7713.2-2022 格式规则与 AI 写作模式清单可单独查阅，但**流水线本身不得启动**。

### 论文写作相关 skill（2026-09-08 新增）

- `humanizer-zh-academic-main`：中文学术写作去 AI 味 / 降 AIGC 检出率。**论文改写的既定工具**，在全文重写完成后**通篇处理一遍**（而非逐章处理——AIGC 检测看的是全文统计规律，逐章做发现不了"各章小结结构雷同"这类特征）。2026-09-12 的六章新稿已按此执行，结果见 `docs/07_Thesis/论文改写方案_1.3万字.md` 第六节"humanizer 处理"。
- `humanizer-document-zh-main`：同类但面向通用中文文档，与上一条重叠。**以 `humanizer-zh-academic-main` 为准**，本 skill 仅在需要前后对照样例时查阅其 `ai 书写示例.md` / `用 skill 修改后的示例.md`；两者的冲突有明确边界（2026-09-09 用一份一万五千字的中文技术文档实测过）：**语义层高度一致**（对模糊归因、泛化结尾、AI 高频词的判断完全同向，可以合用），**冲突全部集中在标点与结构层**——`humanizer-document-zh-main` 禁用破折号、双引号、markdown 小标题与 bullet，而 `humanizer-zh-academic-main` 把破折号当作打散三元并列的改写手段。因此不是"不能同时用"，而是**标点与结构层必须按目标文体二选一**：论文与申报书这类需要靠小标题定位、靠表格核对的文体，一律以 `humanizer-zh-academic-main` 为准。

## 修改规则

- 修改 `docs/02_Architecture/` 中已定义的分层结构或模块划分前，**必须先说明修改原因**（动机、影响范围、替代方案取舍），并更新相应文档，之后才能实施
- 不得在未说明原因的情况下擅自变更已有架构决策
- 修改已有文件前应先理解其上下文，不得随意覆盖或删除已有内容

## 禁止事项

- 项目已进入**维护阶段**（2026-09-10，见 `docs/05_Test/Project_Status_Context.md`）：软硬件主体功能完成并实机验证通过，后续工作以**本地模型的多轮训练**与既有功能维护为主。允许按用户任务要求编写代码，但**只做任务明确要求的范围**，不主动扩大改动面、不顺手重构未涉及的部分；维护期尤其如此——**改动一处就要问一句它是否值得让已稳定的部分重新承担风险**
- 禁止自动安装依赖包，除非用户在当次任务中明确授权（历史先例：安装 dev 依赖、新增 `pyserial` 均由用户显式同意后才执行）
- 禁止生成与任务无关的示例/占位代码；`scripts/` 下的启动组合脚本（如 `run_gui.py`）属于项目正式功能入口，不算此类"示例代码"
- 禁止删除已有文件或内容
- 禁止修改任务未提及的已有文件内容，除非确有必要（如发现真实 bug）且需在回复中说明原因
- 禁止为迎合单一假设的毕设方向而在架构层面做出不可逆的定制化设计
- 每个任务收尾前应运行 `pytest`、`ruff check src tests`、`mypy src` 三项检查，不应在明知未通过的情况下汇报完成
