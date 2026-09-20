# Claude Code Skill 审计报告

> 📌 **本文件分两半读：**
> **第 1~5 节是 2026-08-11 那次审计的存档**，记录当时看到什么、怎么判断、动了哪些目录，
> 内容不回溯修改；**第 6 节维护为当前状态**，随 skill 增减更新。
>
> **现行使用策略以根目录 `CLAUDE.md` 的 "Skill Usage Policy" 一节为准**——
> 那里规定"能不能用"，本文件第 6 节记录"有哪些、在哪个目录"。

> **状态：审计 + 两轮精简已执行（2026-08-11）。** 第 1～4 节为原始审计分析（保留存档，内容未回溯修改）；第 5 节记录实际执行的精简操作与最终状态，以第 5 节为准。所有精简均仅移动 skill 目录位置，未删除任何文件，未修改代码，未修改 CLAUDE.md。

## 审计范围与目标

- **项目定位**：嵌入式设备通用上位机开发平台（Python + PyQt6 桌面应用，STM32 等 MCU 通信，UART/TCP 等通信方式，数据采集与实时可视化，长期维护，未来作为本科毕业设计基础）
- **审计对象**：`.claude/skills/` 目录下全部 14 个 skill（10 个原有 + 4 个近期新增）
- **审计目标**：识别与项目技术方向的相关性、功能重复度、检索负担、技术方向污染风险，并给出分类建议，将**日常 active skill 控制在 10 个以内**

---

## 1. 当前 Skill 总列表

| # | Skill 名称 | 类别 | 新增/原有 |
| --- | --- | --- | --- |
| 1 | pyqt6-ui-development-rules | PyQt6 桌面开发 | 新增 |
| 2 | setting-up-python-libraries | Python 工程化 | 新增 |
| 3 | improving-python-code-quality | Python 工程化 | 新增 |
| 4 | testing-python-libraries | Python 工程化 | 新增 |
| 5 | architecture | 架构图生成（HTML/CSS） | 原有 |
| 6 | uml | UML 图生成（PlantUML） | 原有 |
| 7 | graphviz | 通用图生成（DOT） | 原有 |
| 8 | network | 网络拓扑图生成（PlantUML） | 原有 |
| 9 | iot | IoT 架构图生成（AWS 图标） | 原有 |
| 10 | data-analytics | 数据分析架构图生成（AWS 图标） | 原有 |
| 11 | docx | Word 文档读写 | 原有 |
| 12 | pptx | PPT 读写 | 原有 |
| 13 | pdf | PDF 处理 | 原有 |
| 14 | xlsx | Excel 读写 | 原有 |

---

## 2. 逐个 Skill 审计

### Skill：pyqt6-ui-development-rules
**来源：** GitHub `oimiragieo/agent-studio`（本次会话安装）
**主要功能：** PyQt6 桌面应用 MVC 分层、Signal/Slot 架构、QThread 并发、QSS 主题、响应式布局规则
**适用场景：** 上位机 GUI 开发、界面/业务逻辑解耦、后台通信线程设计
**与当前项目相关程度：** 高
**评价：**
1. 是否建议长期保留：是，项目核心技术栈直接匹配
2. 是否与其他 skill 功能重复：无重复
3. 是否可能增加检索负担：否，触发条件明确（globs 限定 GUI 相关文件）
4. 是否可能造成技术方向污染：否

---

### Skill：setting-up-python-libraries
**来源：** GitHub `wdm0006/python-skills`（本次会话安装）
**主要功能：** Python 项目结构（src 布局）、pyproject.toml、Makefile、CI、pre-commit 规范
**适用场景：** 项目初期工程化搭建、后续新增模块时的目录规范
**与当前项目相关程度：** 高
**评价：**
1. 是否建议长期保留：是
2. 是否与其他 skill 功能重复：与 `improving-python-code-quality` 有少量工具链重叠（ruff/mypy 命令），但侧重点不同（前者管结构与流程，后者管代码质量规则），不构成冗余
3. 是否可能增加检索负担：否
4. 是否可能造成技术方向污染：否

---

### Skill：improving-python-code-quality
**来源：** GitHub `wdm0006/python-skills`（本次会话安装）
**主要功能：** ruff/mypy 配置、类型提示模式、异常处理反模式、确定性/可复现性规范、代码质量检查清单
**适用场景：** 代码审查、类型标注补全、静态检查配置
**与当前项目相关程度：** 高
**评价：**
1. 是否建议长期保留：是
2. 是否与其他 skill 功能重复：否
3. 是否可能增加检索负担：否
4. 是否可能造成技术方向污染：否

---

### Skill：testing-python-libraries
**来源：** GitHub `wdm0006/python-skills`（本次会话安装）
**主要功能：** pytest 测试结构、fixture/参数化/mock、"假绿"测试反模式、覆盖率与 CI 集成规范
**适用场景：** Protocol Layer / Communication Layer 的单元测试、UI 层测试
**与当前项目相关程度：** 高
**评价：**
1. 是否建议长期保留：是，直接对应 `docs/05_Test/Test_Plan.md` 的规划
2. 是否与其他 skill 功能重复：否
3. 是否可能增加检索负担：否
4. 是否可能造成技术方向污染：否

---

### Skill：architecture
**来源：** 第三方 Markdown Viewer 插件（docu.md），随环境预置
**主要功能：** 用 HTML/CSS 生成分层系统架构图（技术栈、微服务拓扑、多层应用设计）
**适用场景：** 绘制 `docs/02_Architecture/System_Architecture.md` 中五层架构的可视化示意图
**与当前项目相关程度：** 中
**评价：**
1. 是否建议长期保留：可保留，但非当前阶段必需（当前架构文档已用文字+树状图描述，暂无强烈可视化需求）
2. 是否与其他 skill 功能重复：与 `uml`、`graphviz` 同属"图表生成"类，功能定位不同（HTML/CSS 布局 vs UML 语义图 vs DOT 有向图），非直接重复，但三者叠加会增加图表类 skill 的检索密度
3. 是否可能增加检索负担：轻度，属于同类工具堆积的一部分
4. 是否可能造成技术方向污染：否，模板本身语义中立（示例偏微服务/Web场景，但工具本身通用）

---

### Skill：uml
**来源：** 第三方 Markdown Viewer 插件（docu.md），随环境预置
**主要功能：** PlantUML 语法生成类图、时序图、状态机图、组件图、用例图、部署图等标准 UML 图
**适用场景：** 绘制协议交互时序图（`docs/03_Communication/Protocol_Design.md`）、PyQt6 MVC 类图、设备状态机
**与当前项目相关程度：** 高
**评价：**
1. 是否建议长期保留：是，是本项目文档体系中唯一能规范化表达"时序图/状态机/类图"的工具，直接服务协议设计和架构文档
2. 是否与其他 skill 功能重复：与 architecture/graphviz 同属图表类，但 UML 语义（类/时序/状态机）是嵌入式协议设计文档的刚需，其余两者无法替代
3. 是否可能增加检索负担：否，触发场景明确（"画类图/时序图/状态机"）
4. 是否可能造成技术方向污染：否

---

### Skill：graphviz
**来源：** 第三方 Markdown Viewer 插件（docu.md），随环境预置
**主要功能：** DOT 语言生成有向/无向图，适合依赖树、调用图、模块层级关系
**适用场景：** 可视化 `docs/02_Architecture/Software_Structure.md` 中的模块依赖关系、通信层与协议层的调用链
**与当前项目相关程度：** 中
**评价：**
1. 是否建议长期保留：可保留，但当前尚无代码可供生成依赖图，属于开发中后期才会用到的工具
2. 是否与其他 skill 功能重复：与 uml/architecture 同属图表类，工具定位不同（通用有向图 vs UML 语义图 vs 布局图），非冗余但存在类别堆叠
3. 是否可能增加检索负担：轻度
4. 是否可能造成技术方向污染：否，工具本身语义中立

---

### Skill：network
**来源：** 第三方 Markdown Viewer 插件（docu.md），随环境预置
**主要功能：** 用 PlantUML + mxgraph 图标绘制网络拓扑（路由器、交换机、防火墙、VPN 等），偏企业 IT/数据中心场景
**适用场景：** 理论上可用于画"上位机 - TCP/IP - 设备"的网络连接示意图，但图标库（Cisco/Citrix/防火墙/数据中心互联）与嵌入式点对点通信场景不匹配
**与当前项目相关程度：** 低
**评价：**
1. 是否建议长期保留：不建议作为 active 常驻，可归档保留以备极小概率的网络拓扑说明需求
2. 是否与其他 skill 功能重复：与 uml/graphviz/architecture 同属图表类，功能可被 uml 的部署图（deployment diagram）基本替代
3. 是否可能增加检索负担：是，图标库贴近企业网络场景，容易在描述"设备通信"时被误召回但给出不相关的路由器/防火墙图标建议
4. 是否可能造成技术方向污染：轻度，可能把"设备间通信"错误引导向企业网络架构语汇，而非嵌入式串口/协议帧场景

---

### Skill：iot
**来源：** 第三方 Markdown Viewer 插件（docu.md），随环境预置
**主要功能：** 用 PlantUML + AWS IoT 图标（IoT Core、Greengrass、Device Defender、OTA 更新等）绘制智能家居/工业物联网/边缘计算架构图
**适用场景：** 表面上与"嵌入式设备""传感器网络"高度贴合，但内容完全基于 **AWS 云端 IoT 服务**（IoT Core、Greengrass 边缘运行时、AWS 设备管理），与本项目"本地上位机 + MCU 点对点通信"的技术路线不符
**与当前项目相关程度：** 低（关键词贴近，但技术内核不匹配）
**评价：**
1. 是否建议长期保留：不建议，除非项目未来明确转向"云端物联网平台"方向
2. 是否与其他 skill 功能重复：与 network/data-analytics 同属"AWS 图标类"图表工具，重复度高
3. 是否可能增加检索负担：**是，风险较高**——skill 描述含"sensor network""edge computing""device management"等词，与本项目描述（嵌入式设备、传感器、边缘）字面高度重合，容易被误触发
4. 是否可能造成技术方向污染：**是，风险较高**——一旦被触发，会引导讨论转向 AWS IoT Core/Greengrass 等云服务架构，而本项目实际是本地 PyQt6 桌面程序直连 MCU，两者技术路线完全不同，容易误导本科毕设的架构方向

---

### Skill：data-analytics
**来源：** 第三方 Markdown Viewer 插件（docu.md），随环境预置
**主要功能：** 用 PlantUML + AWS 图标绘制 ETL 管道、数据湖、实时流处理、数据仓库、BI 看板架构图（Glue、Kinesis、Redshift、Athena、EMR 等）
**适用场景：** 表面匹配"数据采集""实时可视化"，但内容是 **AWS 大数据/云分析栈**，与本项目"本地数据采集 + 桌面端实时波形展示"完全是两个技术方向
**与当前项目相关程度：** 低（关键词贴近，但技术内核不匹配）
**评价：**
1. 是否建议长期保留：不建议
2. 是否与其他 skill 功能重复：与 iot/network 同属 AWS 图标类工具，重复度高
3. 是否可能增加检索负担：**是，风险较高**——skill 描述含"real-time streaming""data acquisition"语义相邻词汇，容易在用户提及"数据采集与可视化"时被误召回
4. 是否可能造成技术方向污染：**是，风险最高**——本项目的"数据采集与可视化"指的是从 MCU 通过串口/TCP 采集数据后在 PyQt6 界面实时绘图，而该 skill 会把讨论引向 Kinesis 流处理、Redshift 数仓、BI 看板等云端大数据架构，属于完全不同量级和方向的技术栈，最容易造成本科毕设方向"跑偏"

---

### Skill：docx
**来源：** Anthropic 官方内置 skill（Proprietary License）
**主要功能：** 创建/编辑/读取 Word 文档（.docx），支持目录、页眉页脚、修订、批注等
**适用场景：** 撰写毕业设计论文、需求文档、开题报告等 Word 交付物
**与当前项目相关程度：** 中（当前开发阶段用不到，论文写作阶段用得到）
**评价：**
1. 是否建议长期保留：建议保留，但非当前阶段 active
2. 是否与其他 skill 功能重复：否
3. 是否可能增加检索负担：低，触发条件明确（.docx / Word 文档相关请求）
4. 是否可能造成技术方向污染：否

---

### Skill：pptx
**来源：** Anthropic 官方内置 skill（Proprietary License）
**主要功能：** 创建/编辑 PowerPoint 演示文稿
**适用场景：** 毕业设计答辩 PPT
**与当前项目相关程度：** 中（未来答辩阶段用得到）
**评价：**
1. 是否建议长期保留：建议保留，非当前阶段 active
2. 是否与其他 skill 功能重复：否
3. 是否可能增加检索负担：低
4. 是否可能造成技术方向污染：否

---

### Skill：pdf
**来源：** Anthropic 官方内置 skill（Proprietary License）
**主要功能：** PDF 读取、合并拆分、表单填写、OCR、加密解密等
**适用场景：** 论文/报告最终导出为 PDF、阅读设备数据手册（Datasheet）PDF
**与当前项目相关程度：** 中（读取 MCU 数据手册场景现在就可能用到，论文导出是后期需求）
**评价：**
1. 是否建议长期保留：建议保留
2. 是否与其他 skill 功能重复：否
3. 是否可能增加检索负担：低，触发条件明确（.pdf 文件相关请求）
4. 是否可能造成技术方向污染：否

---

### Skill：xlsx
**来源：** Anthropic 官方内置 skill（Proprietary License）
**主要功能：** Excel/CSV 读写、公式计算、图表、数据清洗
**适用场景：** 采集数据的导出分析、测试记录表格、性能对比表
**与当前项目相关程度：** 中（数据采集功能实现后可能用于日志导出分析）
**评价：**
1. 是否建议长期保留：建议保留，待数据采集模块开发后价值上升
2. 是否与其他 skill 功能重复：否
3. 是否可能增加检索负担：低
4. 是否可能造成技术方向污染：否

---

## 3. 分类结果

### A. 核心保留 Skills（当前 active，5 个）

| Skill | 理由 |
| --- | --- |
| pyqt6-ui-development-rules | 直接服务 PyQt6 桌面 UI 架构，项目核心技术栈 |
| setting-up-python-libraries | 项目结构/工程规范，与 `Software_Structure.md` 一致 |
| improving-python-code-quality | 类型提示/代码质量，与 `Coding_Standards.md` 一致 |
| testing-python-libraries | 测试规范，与 `Test_Plan.md` 一致 |
| uml | 协议时序图/类图/状态机图，直接服务 `Protocol_Design.md` 与架构文档 |

**当前 active 数量：5 个，满足"控制在 10 个以内"目标，且留有余量。**

### B. 阶段性保留 Skills（当前不用，未来阶段需要，6 个）

| Skill | 预期启用阶段 |
| --- | --- |
| graphviz | 代码量增长后，用于生成模块依赖图 |
| architecture | 架构定稿后，用于制作可视化架构图（答辩/文档展示用） |
| docx | 毕业论文撰写阶段 |
| pptx | 毕业答辩 PPT 制作阶段 |
| pdf | 数据手册阅读（可随时启用）/ 论文最终导出阶段 |
| xlsx | 数据采集模块完成后，用于日志导出与测试数据整理 |

### C. 建议归档 Skills（保留文件但不参与日常检索，1 个）

| Skill | 理由 |
| --- | --- |
| network | 图标库面向企业网络/数据中心，与嵌入式点对点通信场景弱相关；功能可被 `uml` 的部署图基本替代；保留以备极小概率需求，但不应参与日常语义匹配 |

### D. 建议移除 Skills（技术方向污染风险高，2 个）

| Skill | 理由 |
| --- | --- |
| iot | 关键词（sensor/edge/device）与项目描述高度重合、极易被误触发，但内容完全基于 AWS 云端 IoT 服务（IoT Core/Greengrass），会将讨论错误引导至云端架构，与本项目"本地上位机 + MCU 点对点通信"路线冲突 |
| data-analytics | 关键词（real-time/streaming/data acquisition）与"数据采集与可视化"高度重合、极易被误触发，但内容是 AWS 大数据/云分析栈（Kinesis/Redshift/Glue），与本项目"本地采集 + 桌面实时绘图"完全是不同技术方向，是本次审计中风险最高的两个 skill 之一 |

> 注：以上两个 skill 是"关键词强相关、技术内核不相关"的高风险类型——正是最容易在无察觉的情况下污染毕设技术方向的一类 skill，建议优先处理。

---

## 4. 总结建议

1. **当前 active 集合（A 类，5 个）已满足"10 个以内"的目标**，无需从 A 类精简。
2. **B 类（6 个）建议暂缓启用但不删除**——它们对应毕设的后续阶段（论文、答辩、数据导出、架构可视化），过早启用不会有实际收益，过早删除则会在需要时重新查找/安装。
3. **C 类（network）建议归档**——功能可被 uml 部署图替代，日常检索价值低。
4. **D 类（iot、data-analytics）建议优先移除**——不是因为"用不到"，而是因为它们的描述文本与本项目关键词高度重合，存在被误触发后把方向带偏到 AWS 云服务架构的实际风险，风险等级高于单纯的"检索负担"问题。

**（以上第 1～4 节为原始审计分析，形成于精简操作之前；第 5 节记录后续实际执行结果。）**

---

## 5. 执行记录

### 5.1 第一轮（2026-08-11）

根据本报告第 3 节的分类结论，执行了以下精简操作：

- 新建目录 `.claude/archive_skills/`，与 `.claude/skills/` 平级
- 将以下 3 个 skill 目录**整体移动**（非复制、非删除）至 `.claude/archive_skills/`：
  - `network`
  - `iot`
  - `data-analytics`

> 说明：原报告第 3 节将 `network` 单列为 C 类（建议归档）、`iot`/`data-analytics` 单列为 D 类（建议移除）。执行时采用统一的"移入 archive_skills"方式处理三者，因为任务要求"不永久删除、保留恢复能力"——即 D 类的"移除"在不可逆删除被禁止的前提下，实际操作与 C 类的"归档"是同一动作（移出 `.claude/skills/` 检索范围，但文件保留）。

### 5.2 第二轮（2026-08-11，用户追加指令）

用户对第 3 节的 B 类（阶段性保留）给出了两条针对性调整：

- **`graphviz` → 移入 `.claude/archive_skills/`**：与第一轮理由一致，当前无代码可供生成依赖图，属于开发中后期工具，暂不参与日常检索
- **`architecture` → 明确保留在 `.claude/skills/`（active）**：用户说明理由为"项目涉及长期软件架构设计"——即该 skill 服务于 `docs/02_Architecture/` 的长期架构可视化需求，优先级高于原报告第 3 节 B 类的默认"待架构定稿后再启用"判断，故不归档

以上两项均为目录移动，未删除文件、未修改 `SKILL.md` 内容、未修改代码、未修改 CLAUDE.md。

### 5.3 恢复方式

如未来需要重新启用某个已归档 skill，只需将其目录移回 `.claude/skills/` 即可恢复原有的自动检索能力，例如：

```
.claude/archive_skills/network        →  .claude/skills/network
.claude/archive_skills/iot            →  .claude/skills/iot
.claude/archive_skills/data-analytics →  .claude/skills/data-analytics
.claude/archive_skills/graphviz       →  .claude/skills/graphviz
```

移动过程不涉及内容改写，恢复后 skill 行为与归档前完全一致。

### 5.4 两轮精简后的状态（截至 2026-08-11，非当前状态）

**当时的 active skill（`.claude/skills/`，共 10 个）：**

| # | Skill | 分类（对应第 3 节） |
| --- | --- | --- |
| 1 | pyqt6-ui-development-rules | A 核心保留 |
| 2 | setting-up-python-libraries | A 核心保留 |
| 3 | improving-python-code-quality | A 核心保留 |
| 4 | testing-python-libraries | A 核心保留 |
| 5 | uml | A 核心保留 |
| 6 | architecture | B → 用户手动提升为 active（长期架构设计需求） |
| 7 | docx | B 阶段性保留 |
| 8 | pptx | B 阶段性保留 |
| 9 | pdf | B 阶段性保留 |
| 10 | xlsx | B 阶段性保留 |

**当时已归档的 skill（`.claude/archive_skills/`，共 4 个）：**

| # | Skill | 归档原因 |
| --- | --- | --- |
| 1 | network | C：功能可被 uml 部署图替代，与嵌入式点对点通信弱相关 |
| 2 | iot | D：关键词强相关但技术内核为 AWS 云 IoT 服务，方向污染风险高 |
| 3 | data-analytics | D：关键词强相关但技术内核为 AWS 大数据分析栈，方向污染风险高 |
| 4 | graphviz | B → 用户第二轮归档：当前无代码可生成依赖图，暂不参与日常检索 |

**数量统计：**

| 项目 | 数量 |
| --- | --- |
| 精简前 skill 总数 | 14 |
| 当前 active skill 数（`.claude/skills/`） | 10 |
| 已归档 skill 数（`.claude/archive_skills/`） | 4 |
| 精简前后总数变化 | 0（仅移动，无删除） |

> 备注：经两轮精简，`.claude/skills/` 目录下的 active skill 数已从 11 降至 **10**，与"日常 active skill 控制在 10 个以内"的目标口径（物理检索路径中的 skill 总数）精确对齐。

---

## 6. 当前状态（随 skill 增减更新）

> 本节是 `.claude/skills/` 与 `.claude/archive_skills/` 两个目录的**当前实际内容**，
> 与第 5.4 节记录的 2026-08-11 状态不同——那是历史，这里是现在。
> 由 `python scripts/check_doc_numbers.py` 与实际目录逐项比对，不一致会报错。

**最近一次变更：2026-09-08**（论文写作阶段：新增两个中文写作 skill，归档 `autonomous-paper-xts-main`）

### Active（`.claude/skills/`，12 个）

| Skill | 类别 | 用途 |
| --- | --- | --- |
| `architecture` | 开发规范 | 长期软件架构设计（用户指定保留） |
| `uml` | 开发规范 | 类图/时序图/状态机等标准化设计表达 |
| `setting-up-python-libraries` | 开发规范 | Python 工程结构与依赖管理 |
| `improving-python-code-quality` | 开发规范 | 代码质量与重构 |
| `testing-python-libraries` | 开发规范 | pytest 规范 |
| `pyqt6-ui-development-rules` | 开发规范 | PyQt6 MVC 分层、Signal/Slot、线程规范 |
| `humanizer-zh-academic-main` | 论文写作 | **中文学术写作去 AI 味的既定工具**。2026-09-08 新增，已对十章正文通篇处理过一遍 |
| `humanizer-document-zh-main` | 论文写作 | 同类但面向通用中文文档，与上一条重叠。**以 `humanizer-zh-academic-main` 为准**，本 skill 仅在需要前后对照样例时查阅 |
| `docx` `pptx` `pdf` `xlsx` | 阶段性 | 论文、答辩材料与数据导出。物理保留在 active 目录，但不属于"核心开发规范" |

CLAUDE.md 的 "Active Development Skills" 列的是上表前六个——**那是"允许主动调用"的清单**，
论文写作两个另有使用约定（去 AI 味应在十章重写完成后**通篇处理一遍**，而非逐章），
`docx` 等四个属工具性质、按需使用。

### Archive（`.claude/archive_skills/`，5 个）

| Skill | 归档时间 | 原因 |
| --- | --- | --- |
| `network` | 2026-08-11 | 功能可被 uml 部署图替代，与嵌入式点对点通信弱相关 |
| `iot` | 2026-08-11 | 关键词强相关但技术内核是 AWS 云 IoT，方向污染风险高 |
| `data-analytics` | 2026-08-11 | 同上，技术内核是 AWS 大数据分析栈 |
| `graphviz` | 2026-08-11 | 当时无代码可生成依赖图（第二轮追加归档） |
| `autonomous-paper-xts-main` | **2026-09-08** | 它是"给定主题 → 自动检索文献 → 并行写作 → 产出约 1.2 万字论文"的全自动流水线，与本项目处境**正好相反**：本项目已有基于真实实测数据的论文，要做的是压缩与补写，不是重新生成。启动它等于用检索来的综述替换掉四周积累的实测记录。其 `references/` 下的 GB/T 7713.2-2022 格式规则与 AI 写作模式清单可单独查阅，**流水线本身不得启动** |

归档只是移动目录，**未删除任何文件**，恢复方式见第 5.3 节。

### 与 `docs/README.md` 的关系

`docs/README.md`「开发环境说明」一节概述的是**开发规范类** skill（上表前六个中的
Python 工程化、PyQt6、UML 三类），不含论文写作与工具类——那是概述的取舍，不是遗漏。
