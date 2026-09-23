# 项目状态归档（Project Status Context）

> 本文档是为"开启新 Claude Code 会话继续开发"而生成的**状态快照**：它回答"现在做到哪了"，
> 不回答"怎么走到这里的"。过程记录在 `status/` 下的分卷里，叙事体推进记录在
> [`../01_Project/项目推进日志.md`](../01_Project/项目推进日志.md)。
> 所有数字都经 `pytest`/`ruff`/`mypy` 实跑核实，不作推测。

## 一句话现状（2026-09-09，论文与测试数字 2026-09-14 订正）

软件三端（PC 界面 / Android / 板载 LCD）与三个传感器通道全部完成并在真实硬件上验证通过；
五项扩展功能（自动通风、语音告警、板载 LCD、环境问答、历史记录与归档上云）已实现并实机通过
（除 PC 下发报警状态一项，用户判断意义不大）；环境问答覆盖 PC 与手机两端，
**四档交互性做完前三档**（多轮指代、反问澄清、模型写接地解释），87 句题库实测 **84/87 = 96.6%**（指令类与范围外各 100%；未过的 3 条同属「裸开关」一类，见 [`baseline/`](baseline/)）。**这是拟合题库上的数**：2026-09-14 用 148 句未参与调词表的留出题复测，规则范围内正确 **82.8%**、18 句自信地答错，模型直接分类 91.0%，错误执行成指令 0 次（唯一一次已修复），详见 [`baseline/README.md`](baseline/README.md)"留出题库"；
**2026-09-23 新增浏览器控制台 `web/`**（网关的第三个客户端，与 Android 同性质，设计见 [`Web_Console_Design.md`](../02_Architecture/Web_Console_Design.md)）：实时监测与风扇控制、串口链路检视、问答全过程追溯、历史曲线四个页签；连不上网关时回放真实实测数据（一小时实验 3489 帧、故障注入会话、模型问答实录），可直接双击打开或发布到 GitHub Pages。配套新增 `--mode virtual`（进程内虚拟 STM32 经无消息边界的字节管道接真实接收链路，`--inject-faults` 故意制造拆帧/并帧/杂散字节/CRC 翻转）与网关的通风、链路、问答追溯接口。自动化测试 **1348 项**全绿，`mypy` **99 个源文件**无问题。过程见 [`status/移动端与网关记录.md`](status/移动端与网关记录.md) 5.6 节。

**论文 2026-09-23 按导师意见重构为新的六章**（绪论／系统总体设计／**硬件设计**／软件设计／系统测试／结论与展望，骨架照导师指定的模板 `docs/杨.docx`）：硬件独立成第 3 章并按八个模块配原理图，环境问答助手由独立一章降为第 4 章 4.5 节（设计与六项算法优化），评测数据移到第 5 章 5.6 节做优化前后对比，设计章不再出现测试。正文 23,627 汉字、38 张图、30 张表，合并稿 docx 与答辩 PPT 均已重新生成。重构前的七章稿完整备份在 `07_Thesis/归档/七章稿_20260923重构前/`，过程见 [`status/论文与交付物记录.md`](status/论文与交付物记录.md) 5.6.5 节。以下为 09-12 那次改写的记录，章号已过时：

**论文 2026-09-12 改写为六章**（新稿在 [`07_Thesis/重写_1.3万字/`](../07_Thesis/重写_1.3万字/)）：主线暂定抽象为"把不可靠的部件放在不承担正确性责任的位置"，协议可靠性与环境问答助手是它的两个实例，助手升格为独立的第 4 章并作为核心创新点（见 [`Project_Overview.md`](../01_Project/Project_Overview.md)"论文主线的抽象"一节）。正文约 **18,508 字**（2026-09-15 按"中文字符含标点 + 英文/数字单词、引用编号不计"重算；台账 09-14 记为 17,687，其后第 4、5、6 章改动未回填，差异表见改写方案），26 张图、24 张表，已通篇做过 humanizer，排版脚本已改为读新稿并能跑通。**正文 1.5 万字已确认为学校要求**（2026-09-14 与导师确认），1.3 万的上限作废。现行计划与台账见 [`论文改写方案_1.3万字.md`](../07_Thesis/论文改写方案_1.3万字.md)。此前十章稿"约 3 万汉字"的口径说明已移入 [`status/论文与交付物记录.md`](status/论文与交付物记录.md) 5.6.1 节；
自动化测试 **1315 项**全绿（2026-09-21 实测，连跑多遍；较 09-18 的 1266 增 49：上云脚本的 `--slot`、启动器改中文名的守卫，以及**当前时段快照 `--snapshot`** 与按钮 runner 的用例）。此前 1266 项（2026-09-18 实测，较 09-17 的 1210 增 56：仪表盘分页、历史区分三列与按通道定小数位，以及**删除的拒绝与上传的按钮**），Android 侧 **41 项**全过（较 09-17 的 40 增 1），`ruff` 全过，`mypy` **97 个源文件**无问题。此前：1019 项（2026-09-17，含征询语气守卫 3 项、指令模型复核 7 项、复合句拆句 12 项与问答日志 10 项回归），`mypy` 88 个源文件；`src/` 共 13783 行（问答日志落在 `scripts/`，不计入 `src/`）。

~~**三处固件改动已在源码里但未烧录**：噪声首帧丢弃、屏幕构建标记删除、LCD 第二页。~~
**2026-09-18 作废并已实测闭环**：三处改动早已烧录（实机图已进论文 docx）；同日复跑一小时稳定性实验，**噪声首点 40.8 dB(A)，与其后最小值 40.00 齐平，伪值不再出现**（此前两次实验的首点是 84.70 与 96.20）。同轮 3489 帧、三通道各 1163 次、丢帧 0、Modbus 应答 1163/1163 = 100%、帧同步错误 0，实测周期 3.097 s（σ=0.023）。数据在 [`../07_Thesis/实验数据/长时间稳定性_20260918_183404.csv`](../07_Thesis/实验数据/长时间稳定性_20260918_183404.csv)。论文据此改定：第 6 章设计层面的不足由四处减为三处，"在固件中丢弃首次读数"从后续工作移走；**第 5 章那批数据仍按"排除首点"处理不变**——它采于修复之前，数据必须与采集它时的固件行为对应。

**2026-09-10 起进入维护阶段。** 软硬件主体不再新增功能，后续工作是**本地模型的多轮训练**与既有功能的维护修补。训练相关的落点尚未决定，见「下一步：当前优先级」的开放问题一节。

## 怎么用这份文档

| 想知道 | 看哪里 |
| --- | --- |
| 接下来该干什么 | 本文件「下一步：当前优先级」 |
| 怎么把项目跑起来 | 第 0 节 |
| 某一层实现到什么程度 | 第 2 节 |
| 测试/检查基线 | 第 3 节 |
| 数据怎么流动的 | 第 4 节 |
| 还有什么没做、什么等我拍板 | 第 5 节、第 5.3 节 |
| 某个功能当初为什么这么做 | `status/` 下对应分卷 |
| 哪一天做了什么 | [`../01_Project/项目推进日志.md`](../01_Project/项目推进日志.md) |

---


> 📐 **章号口径（2026-09-18 订正后）**：本文件中**当日之前写下的**「第 7／8／9／10 章」「图 4-1」这类引用是**十章稿的编号**，写下时是准确的，因此保持原样不改——改了就是改写记录。新旧对照：**第 5 章固件／第 6 章协议／第 7 章上位机／第 8 章移动端 → 第 3 章；第 7 章 7.8 问答 → 第 4 章；第 9 章测试 → 第 5 章；第 10 章总结 → 第 6 章**（完整对照见 [`../07_Thesis/论文改写方案_1.3万字.md`](../07_Thesis/论文改写方案_1.3万字.md) 与 [`../07_Thesis/插图/图号映射_七章稿.md`](../07_Thesis/插图/图号映射_七章稿.md)）。**面向读者的现行文档已全部订正为六章编号**，本文件属过程记录，不在其列。

## 分卷索引（2026-09-09 拆分）

本文件曾长到 1712 行，其中过程记录占了大半——而新会话需要的是**当前状态**，不是每一步是怎么走到这里的。因此按"状态留下、过程移出"拆分如下；
**只搬运、未删改任何内容**，需要追溯细节时按下表打开对应分卷。

| 分卷 | 内容 |
| --- | --- |
| [`status/扩展功能与问答实施记录.md`](status/扩展功能与问答实施记录.md) | 2026-09-07 起四项扩展功能（自动通风、语音告警、板载 LCD、环境问答）以及问答四档交互性的完整实施过程，含踩过的坑与实测数字。 |
| [`status/硬件实机记录.md`](status/硬件实机记录.md) | 传感器到货、接线、实机验证与固件烧录排障。 |
| [`status/移动端与网关记录.md`](status/移动端与网关记录.md) | PC↔Android 的架构决定，以及 Android 两个阶段的实施与验证状态。 |
| [`status/论文与交付物记录.md`](status/论文与交付物记录.md) | 论文各阶段进度、2026-08 下旬的七份交付材料，以及 09-07 的需求方向转变。 |
| [`status/早期归档.md`](status/早期归档.md) | 已完成或已作废、但仍有追溯价值的记录。 |

另有两份长期文档与本文件并列，未参与本次拆分：[`../01_Project/项目推进日志.md`](../01_Project/项目推进日志.md)（叙事体推进日志）与 [`../09_STM32Hardware/STM32F407_硬件落地方案.md`](../09_STM32Hardware/STM32F407_硬件落地方案.md)（固件侧方案与实机记录）。

## 下一步：当前优先级（2026-09-09 重排）

**未完成，按建议顺序：**

| 顺序 | 事项 | 说明 |
| --- | --- | --- |
| ⚠ | ~~**引导性提问会被执行成指令**~~ | ✅ 2026-09-14 修复：规则层新增 `_CONSULTATIVE_WORDS`（是不是该／要不要／对吧／假设……），在 `_fan_intent()` 中先于所有指令分支判定，问阈值的答阈值、其余答风扇状态（该档事实本就含阈值与读数），**32 句鲁棒性题错误执行 5 → 0**，三条真实指令不受影响，留出题库逐项不变。同日**模型复核（该方案阶段一）也已实施**，见本表下方 09-14 条目与 [`Intent_Review_Proposal.md`](../02_Architecture/Intent_Review_Proposal.md)；只剩阶段二（复核问题类）未做，等真人试用数据 |
| 0 | 与导师确认题目（2026-09-12 起） | 篇幅已闭环：**2026-09-14 确认正文 1.5 万字为要求**，现稿扩写后 09-14 记为 17,687，09-15 重算约 18,508，见 [`论文改写方案_1.3万字.md`](../07_Thesis/论文改写方案_1.3万字.md) 第六节。题目：主线已改，题目是否跟着调整仍待确认 |
| 1 | ~~交叉引用章号统一订正~~ **2026-09-18 完成** | 实扫全部现行文档：真正指错的是 **8 份、24 处**，已逐条按六章结构订正（`附录A_关键算法代码.md` 4、`关键代码实现讲解.md` 5、`Test_Plan.md` 3、`STM32F407_硬件落地方案.md` 4、`上板联调与测试手册.md` 1、`Assistant_Design.md` 1、`项目代码结构导览.md` 1、`第二阶段_UI优化方案.md` 1，另有若干处顺带补全了小节号）。**其中 `附录A_关键算法代码.md` 最要紧——它本身就是论文的「附录 A」，错的章号会随论文一起交出去。** 未改的三类均属刻意：①过程记录与写作期文件（本文件、`论文改写方案`、`待人工核实清单`、`中文文献检索清单`、`参考文献候选库`、`论文待办总清单`）写下时是准确的，改了就是改写记录，各自加了章号口径说明；②`答辩问答准备.md` 的旧编号全部在**新旧对照表**里，那正是它们该在的地方；③`Project_Overview.md` 那句"由第 7 章 7.8 一节升格"描述的就是这次变更本身。原估"约 55 处"是按正则粗数的，含大量本就正确的六章引用 |
| 2 | ~~排版~~ **2026-09-18 核对：早已不是待办** | 学校模板（附件 6 封面、附件 7 正文）**2026-09-10 就已到手并放在 `docs/` 下**，`build_thesis_docx.py` 当日即按模板实现了页边距、对称装订、章首奇数页、页眉页脚、前置罗马数字页码、字体字号行距、图表题、引用上标、参考文献悬挂缩进、诚信声明书与 TOC 域，逐项对照见 [`../07_Thesis/排版规范对照.md`](../07_Thesis/排版规范对照.md)。**本行此前一直写着「等学校模板」，停在 09-10 之前的状态。** 现仅剩三项必须在 Word 里人工做：①全选按 F9 更新目录页码（python-docx 不分页，脚本算不出页码）；②翻页确认奇偶页与总页数；③诚信声明书签字、致谢正文，以及参考文献按 GB/T 7714 逐条核对著录格式（脚本只统一了编号与方括号，未改条目正文） |
| 2.5 | ~~论文里的问答准确率改为两组并列~~ | ✅ 2026-09-14 完成：新稿第 5 章新增 5.6 节（留出题库三种处理方式对照 + 32 句鲁棒性测试），5.5 节末、5.8 节局限、第 6 章与中英文摘要同步并列写出。**答辩材料尚未改**，随第 3 项一起做 |
| 0.5 | ~~**87 句基线要带模型重排一次**~~ | ✅ 2026-09-14 完成，见下方当日条目与 [`baseline/README.md`](baseline/README.md)"守卫与复核上线后的重排"。结论：**84/87 逐项不变，复核零误报，整轮 6.1 分钟** |
| 3 | 答辩材料按六章新稿重做 | **PPT 已完成**（2026-09-15）：`build_defense_pptx.py` 按六章与新主线重写，44 页，正片按论文章节排、第 4 章助手 6 页为核心，四个实测缺陷升入正片，另有 10 张备用页（含"为什么不让大模型直接控制设备""复合句拆句测试"）；图题编号与六章稿一致，版式自检通过。**演讲稿已完成**（同日）：`答辩演讲稿.md` 按新 PPT 页序 P01–P25 重写，15 分钟，时间向第四部分助手倾斜，附压缩顺序与备用页 P26–P35 对照表，docx 由 `build_code_guide_docx.py` 导出（该脚本 09-15 修复了对已删除函数 `set_default_fonts` 的导入）。**问答准备已完成**（同日）：`答辩问答准备.md` 章节号换为六章编号并附新旧对照表；30 秒／2 分钟陈述与 Q3 按新主线改写；新增 H 组 11 题（助手）与 C9、E5、F5；订正 Q1 中"GB 37488 为强制性国标、适用范围列有轨道交通站台"的错误（所引三条均为推荐性条款，站台只见于 4.1.5.2 条文）、"报警不设回差"（回差与 2 周期确认已实现）、"缺文献支撑"等过时说法；Q2 写明噪声首帧丢弃已在固件源码中但未烧录。**第 3 项至此全部完成**。**2026-09-17 再次更新**：历史记录与上云补进 PPT 正片（第 3 章新增「第五项扩展：历史记录与归档上云」一页，正片 25 → 26 页；第 5 章质量页加"3 个时段真实上传至 OSS"指标卡；提纲页第 03 条补"历史与上云"）。演讲稿相应顺移 13 个切页标记、新增 P13 讲词、备用页改 P27–P36、时长表按实测重排为 14:30。三份产物均已重新生成，PPT 版式自检通过。**2026-09-17 复核并重新生成**：论文与答辩材料中的自动化测试数由 1009 统一改为 1019（当日复跑实测 `1019 passed`），连带分层分项「脚本 134→144」、「上位机部分 984→994」与复跑日期一并订正，共 5 个文件 11 处；三份产物（`毕业答辩.pptx`、`答辩演讲稿.docx`、`毕业论文正文合并稿.docx`）已重新生成并逐一验证内含数字，PPT 内 1019 两处、旧值零处。另修 `build_defense_pptx.py` 一处真实缺陷：成功提示里的 `✓` 在默认 GBK 控制台下抛 `UnicodeEncodeError`，且崩在 `prs.save()` 之前导致产物根本不落盘，已改为 ASCII 提示 |
| ✅ | ~~**模型触发上传与删除**~~ | **2026-09-18 完成**，设计见 [`History_And_Cloud_Design.md`](../02_Architecture/History_And_Cloud_Design.md) §6.1／6.2。**上传走按钮方案**：新意图 `CLOUD_SYNC_HINT`，助手只读台账答出"还有 N 个时段没传"，桌面端答案底下出现「导出并上传」按钮，点击才拉起 `cloud_sync.py` 子进程；台账经 `ExportStatus` 协议注入（协议定义在消费方 `service/assistant/export_status_port.py`，适配器在 `application/export_status.py`——`service` 不得 import `storage`），**给出的只是一个整数，助手没有任何上传能力**；按钮只给桌面端，手机端不给。**删除做「认出但拒绝」**：新意图 `DELETE_REQUEST`，与播报同一档、**不给按钮**——09-17 已经判定按钮对删除太弱（"清空历史记录"因此被收窄成只清显示），再让模型去点亮它等于把否掉的方案装回来。它同时堵住一个已存在的坑：数据紧挨通道词，"把噪声数据清一清"此前会被答成一个真实声压级。**发现两处文档与代码不符**：6.1 节写着"P3 时做"，而 P3（09-17）交付时这一块其实一行都没实现 |
| ✅ | ~~**问答日志**~~ | **2026-09-17 完成**。起因：题库造不出真人语料，而项目里真正有价值的缺陷全部来自真人试用（09-08 答案错位、09-09"开风扇"认不出、09-15 一句话两件事），以前问完就没了。落点 `scripts/question_log.py`：一问一答一行 JSONL，配对"立即的模板答案"与"迟到的模型改写"，按天分文件、**按提问时刻归档**，写在 `logs/assistant/`（已入 `.gitignore`）。**`src/` 零改动、未扩接口、无新依赖**——`LoggingApi` 继承 `LocalApi` 只覆盖 `ask()`，接线在 `automation_wiring.py`，三个启动器共用。顺带补上了 `run_api_server` 此前**根本没有设置提问观察者**的漏洞（手机在那个启动器下问的话无人看得见）。**不上板载屏、不推手机**：屏幕只显示系统能负责的读数。10 项回归测试 |
| ✅ | ~~**本地历史记录**~~ **2026-09-17 全部完成（P0～P3）**，设计见 [`History_And_Cloud_Design.md`](../02_Architecture/History_And_Cloud_Design.md) | **已交付**：读数写本地 SQLite（重启不丢）、桌面与手机经同一套接口查历史、按整点导出归档、手动触发上传至 OSS（**真实上传已验收**）；论文与答辩材料已同步走完一轮。以下为实施前的规划，保留以存时间线——存储实现落在**新增顶层包 `src/storage/`**（方案 A，已确认；实施时须同步改 `CLAUDE.md`、`Software_Structure.md`、`docs/README.md` 与新包 README 四处）。服务层加一个订阅数据的记录器（`sqlite3`，标准库，无新依赖），接口层加查询方法（**需授权扩展 `ApiInterface`**），网关补历史端点（要改 `tests/gateway/test_server.py` 里那条断言 404 的用例），界面改为经接口取数。数据量约 8.4 万条/天、一年几十 MB。**对 LLM 侧无直接影响**：取数层读的是 `SensorDataProcessor` 的内存统计，不经过数据服务；但 `phrasing.SCOPE_NOTICE`（"只保留本次运行以来的数据"）会变成假话，须改文案，涉及 `test_phrasing.py` 3 处断言。让问答能查历史属第二步，会改分类提示词并作废模型基线，暂不做。**2026-09-17 追加：手机端也要能看历史**，沿用 `PC_Android_接口设计.md` 2.3 节既有契约，Android 侧加 `queryHistory()` 与一个仿 `AssistantActivity` 的历史页，WebSocket 不动 |
| ✅ | ~~**数据上云（只存不算）**~~ **2026-09-17 完成并实测**（设计见 [`History_And_Cloud_Design.md`](../02_Architecture/History_And_Cloud_Design.md) 第 5 节） | 2026-09-16 确定：本地处理完再**定时打包成文件**上传，云端不参与计算、不接远程控制。落点为**阿里云盘（个人网盘）**。断网补传直接复用第 4 项的历史库当待发队列，**故必须排在历史记录之后**。**2026-09-16 定案**：走**对象存储 OSS**（`oss2` 2.19.1 已装在 `D:\PyPkgs`），不走阿里云盘——云盘那条路上传由客户端代劳、系统本身不含上云能力，开放平台直传又要开发者审核与令牌刷新。**每小时导出一个 CSV**，上传器在 `application`/`scripts` 内创建，网络 IO 不得放进数据回调（09-07 回调内下发命令重入串口的教训）。Bucket 与 RAM 子账号密钥待用户创建（2026-09-17 已填好 `oss_config.json`），P0～P2 不需要它。入口为根目录 **`cloud_sync_导出并上传.bat`**（手动双击触发，系统运行期间无定时器、无后台上传）。数据落点：历史库 `data/history.sqlite`、归档 `exports/`，均不入库。**能否用一句话让模型触发上云：不进指令白名单**（不可逆、拉子进程、参数说不清，三条准入性质全不满足，与播报被拒同理），改用**按钮方案**——模型出标签、界面出按钮、人点击才执行，见设计文档 6.1 节。**2026-09-17 改定：整项排在答辩之前完成并交付**（与导师商定），且**上云验收形态为答辩现场演示上传**，须另备断网退路。设计文档第 0 节记录了这四项变更 |
| ✅ | ~~**手机端看历史**~~ **2026-09-17 完成** | `HistoryActivity`，JVM 单测 40 项全过。注意这与下一行取消掉的"离开局域网看云上历史"**不是同一件事**：手机查的是 **PC 本地历史库、经局域网网关**（沿用 `PC_Android_接口设计.md` 2.3 节早已写好的契约），**不直连云端**，因此仍不需要 STS 临时凭证，OSS 密钥仍只在 PC 一端。上云按钮仍不给手机（手机看不到子进程输出）。答辩问答 F4 已整条重写 |
| — | ~~**手机离开局域网看云上历史**~~ | **2026-09-16 取消**（用户决定），**2026-09-17 仍然取消**——手机看历史改走局域网网关，见上一行。评估结论：走阿里云盘需开发者认证 + OAuth（移动端 PKCE）+ 令牌 30 天刷新，且第三方实践记录到按 IP 限流与"多 IP 访问可能触发账号风控"，而答辩演示正是多设备访问；备选 OSS（Android SDK + STS 只读凭证）**用户明确不走**。手机端因此维持现状：局域网直连网关，不看历史。~~答辩问答 F4 的现有回答继续成立~~ → **2026-09-17 作废**：历史能力已定为交付功能且手机端要能看，F4 必须整条重写 |
| — | **参考文献** | **按用户决定另立项目，最低优先级** |

**维护期的开放问题（2026-09-10，待训练工作启动时决定）：**

| 问题 | 为什么现在还不能定 |
| --- | --- |
| ~~训练代码放哪里~~ **2026-09-18 已定：顶级目录 `training/`** | 与 `firmware/`、`android/` 同性质——独立工具链、离线生命周期，不进 `pytest`/`mypy src`，依赖不写进 `pyproject.toml`；`src/` 与 `training/` 互不 import，交接面是 Ollama 的模型名。原因记录保留：`src/llm/` 是**运行期适配层**，只能由 `application`/`scripts` 创建、不得被 `service` import，放进去会让一个受约束的适配层同时承担两种矛盾的生命周期。约定见 [`../../training/README.md`](../../training/README.md) |
| ~~训练产物怎么管~~ **2026-09-18 已定** | `training/runs/<日期>_<模型>_<轮次>/` **一轮一个目录、不覆盖**，权重与配置快照放一起；`training/datasets/` 放训练与评测集。两者都已写进 `.gitignore`（训练集可能含真人原话，与 `logs/` 同因）。**不覆盖**这一条是重点：第二轮盖掉第一轮就再没有可比基线，而能不能比较正是这件事唯一的判据 |
| 用什么衡量"训练有没有变好" | 抓手是 `scripts/assistant_benchmark.py` 与 87 句题库。**基线已于 2026-09-10 存档**：[`baseline/问答基线_20260910_qwen3.5-4b.txt`](baseline/问答基线_20260910_qwen3.5-4b.txt)，84/87 = 96.6%，规则命中 87/87，改写采纳 49/87，中位 4.9 s。归档规则与配置见 [`baseline/README.md`](baseline/README.md) |
| 换模型后边界是否仍成立 | `docs/02_Architecture/LLM_Boundary.md` 的四层约束里，①②与模型无关，③④与模型强相关——换模型后温度与提示词的实测结论需要重测 |

**已按用户决定不做（2026-09-09）：**

| 事项 | 决定与理由 |
| --- | --- |
| 移动端重连后重新拉设备列表 | **不做**。用户：硬件展示只有一台设备，修它没有意义。第 10 章仍如实列为不足，但补注了适用范围——单设备部署下不会显现 |
| 历史数据持久化 | **作为后续工作讲**，不在答辩前做。第 10 章 10.3 列为不足、10.4 列为展望，两处均已就位 |

**已闭环（2026-09-09）：**

| 事项 | 结果 |
| --- | --- |
| ~~固件重新烧录~~ | ✅ 用户已烧，LCD 实机确认显示正确。ROM 与固件自研行数已据新产物回填，[`待人工核实清单.md`](../07_Thesis/待人工核实清单.md) 该节改为已闭环 |
| ~~静默失连测试~~ | ✅ 判定抽为 `StallDetector`（纯 Kotlin、零 Android 依赖），补 9 个用例覆盖边界；中文路径跑不了 JVM 单测，按既有办法复制到英文临时路径 `testDebugUnitTest` 全过（含原有 MessageParser 13 项）|
| ~~报警确认不一致~~ | ✅ 确认下沉到 `SensorDataProcessor`，界面/LCD/语音三方对齐；另加解除回差 |
| ~~Android 问答页真机验证~~ | ✅ 用户实机验证通过，无问题。界面就此定稿，三张截图类插图解除阻塞 |
| ~~补拍三张界面截图~~ | ✅ 2026-09-09 用户拍来六张，处理为四张插图：图 7-2（PC 主界面，含通风面板/风扇卡/问答面板）、图 8-2（Android 主界面 + 问答页并排）、图 9-6（PC 与手机 **21:21 同刻**，25.0/56.9/72.6 对 25.0/57/72.6）、**新增图 5-2**（实机 LCD 两页，论文原本一张 LCD 图都没有）。只做裁剪缩放拼接，未修改画面内容 |
| ~~插图核查与重画~~ | ✅ 查出六张有问题。四张脚本生成的示意图（图 2-1／4-1／5-1／7-1）已按现状重画，其中**图 2-1 原本画错了架构**——从网关引一条箭头到本地语言模型，而模型由 `application` 创建、供问答措辞用，网关根本不碰它。另补回六张图的引用：第 9 章原先只有 1 处图引用（图 9-2~9-6 五张已画好却从未被引用，而 PPT 在用），第 8 章正文一张图都没有。现 **22 张图文件与 22 个图号一一对应**（2026-09-09 复核：图 5-2「采集端本地显示的两页」在 LCD 第二页落地后补入，此前记的 21 已过期） |
| ~~答辩 PPT 优化~~ | ✅ 强调色对比度 3.22→7.48（原色是从上位机**深色**主题搬来的，换底色却没换强调色）；最小字号 10→12 pt；散文字数中位 227→159；21 页超载清零。版式规约写成会失败的 `verify()`，`strict` 已开 |

**2026-09-08~09 已完成**（详情见 [`status/扩展功能与问答实施记录.md`](status/扩展功能与问答实施记录.md)）：

| 事项 | 一句话结论 |
| --- | --- |
| **报警确认下沉 + 回差（2026-09-09）** | 此前 `ThresholdStatus.triggered` 逐点算出，界面高亮与 LCD 位图立刻响应，而语音要连续两次才播——**同一系统内部对"什么算报警"有两套标准**。确认下沉到 `SensorDataProcessor`（`confirm_cycles=2`，只管建立、解除仍立即），播报器默认值相应改为 1。另给 `AlarmBand` 加解除死区（湿度 0.5%RH / 温度 0.3℃ / 噪声 1.0dB）|
| **11 份记录回放验证（2026-09-09）** | 逐点 15 段报警 → 仅确认 12 段 → 加回差仍 12 段。**整段消掉 3 段全是长度 1**：噪声 96.2 与 84.7（首帧伪值）、湿度 75.01（阈值抖动）。12 段真实报警一段没少。**回差在本批数据上无额外收益**——两个机制互相抵消，详见 `Assistant_Design` 同批实测的记法，结论如实写在代码注释里 |
| **真人试用查出三个 bug（2026-09-09）** | 三个全是我自己引入的，且模式一致——**做了一半就收手**：①「你能告诉我温度多少」被当成「你能干什么」（占位答复的判据用了 `_HELP_WORDS` 里的**片段**，"你能"命中即回清单且**不叫模型**——这正是占位答复要消灭的死角，却在它前面新开了一个）；②裸开关反问**只做了问、没做接**，用户怎么回都接不住，只能整句重打；③通道记忆**只做了一半**，"温度最高值是多少 → 噪声呢"答成噪声当前值。已各补一组回归测试，并穷举 22 种输入确认**死角归零** |
| **模型边界汇总文档（2026-09-09）** | 新增 [`docs/02_Architecture/LLM_Boundary.md`](../02_Architecture/LLM_Boundary.md)：四层约束从硬到软（结构 / 出口校验 / 采样参数 / 提示词），各自拦住什么、实测触发率、代价多少。核心一句：**信任它组织语言，不信任它承担事实** |
| **模型启动脚本（2026-09-09）** | 新增 `scripts/start_llm.py` 与 `start_llm_启动本地模型.bat`。起因：Ollama 在本机不是系统服务而是靠启动文件夹自启，且**服务活着不等于模型可用**——首次推理要从磁盘载入 3.4 GB，实测 **8.8 s**。开发期间机器一直没关机，这段延迟从未暴露过。脚本探测服务→按需拉起→确认模型已下载→**发真实请求预热**，退出码可直接用于批处理前置判断。写时撞到一个坑：只读 `os.environ` 会误报"变量未设置"（本终端早于变量设置时刻打开），改为读用户级注册表并区分"设了没有"与"本进程继承到没有"。补 10 项单测（2026-09-14 实测 `test_start_llm.py` 为 16 项） |
| **模型停止脚本与根目录入口（2026-09-10）** | 新增 `scripts/stop_llm.py` 与根目录 `stop_llm_停止本地模型.bat`，`start_llm_启动本地模型.bat` 也复制到根目录，和 `run_all_界面加网关.bat` 等入口放在一起（`scripts/start_llm_启动本地模型.bat` 保留为旧入口）。起因：`OLLAMA_KEEP_ALIVE = -1` 下模型载入后**永远不会自己退出**，3.1 GB 内存一直占着。两级停法：默认只卸载模型、服务保留；`--server` 连 `ollama.exe` 与托盘程序一起结束（只杀服务的话托盘程序会把它重新拉起来）；`--status` 只看不动。不删除任何模型文件。`test_stop_llm.py` 10 项。说明见 [`LLM_Boundary.md`](../02_Architecture/LLM_Boundary.md) 第七节 |
| **留出题库与一处指令误判修复（2026-09-14）** | 起因：87 句题库全被规则命中，模型分类从没被测到，泛化能力没有数据。用模板生成 148 句新题：规则范围内 82.1%，**19 句自信地答错**，其中"风扇让系统自己决定开关"在真实组合里**把风扇切成了手动常关**。按用户决定**只修这一处有副作用的**：`_FAN_AUTO_WORDS` 补"系统决定"等说法，`_FAN_STATE_WORDS` 加"是系统/决定的吗"问句守卫（误判方向偏向当成提问），补 2 项回归测试；修后范围内 82.8%，错误执行 0，87 句基线不变（84/87）。其余错判登记为已知局限。同批试了 Ollama JSON Schema 约束输出：快一倍多但准确率没提升，还多出一次错误执行，**不采用**。全部数据与脚本在 [`baseline/`](baseline/) |
| **同类开源实践检索（2026-09-14）** | 复核做完后查了一轮同类系统，记在 [`同类开源实践参考.md`](../02_Architecture/同类开源实践参考.md)。三条与本项目同构（Snips NLU 的"确定性解析器在前、概率解析器在后"、Rasa 的两阈值回落与 Two-Stage Fallback、Home Assistant Assist 的"优先本地处理"+暴露实体白名单），说明规则优先与白名单都是通行做法而非本文的临时选择；一条取向相反（`xiaozhi-esp32` 经 MCP 让模型直接控制设备），是答辩问"为什么不直接用大模型控制设备"时最具体的回答对象；一条指向评测短板（中文智能家居拒识基准 11,913 条 13 类，本项目范围外只有 14 句）。**另有一处可改进方向记在案**：Rasa 用置信度之差判歧义、OVOS 按置信度分档，而本项目规则侧给不出置信度，只能二值裁决，误报率没有旋钮——阶段二若要做必须先解决 |
| **87 句基线重排（2026-09-14，守卫与复核之后）** | 带模型重排，归档 [`问答基线_20260914_qwen3.5-4b.txt`](baseline/问答基线_20260914_qwen3.5-4b.txt)。**逐项与 09-10 相同**：84/87、问 54/57、指令 22/22、范围外 8/8、规则命中 87/87、改写采纳 49/87。三点新信息：①**复核在 22 条指令上零误报**（一条都没被反问拦下），所以"指令多等几秒"之外没有额外代价——但这是拟合题库，指令说法都是规则认得出的标准说法，不能外推到真人口语；②**模型请求 63 → 88，正好多 25**（22 条指令 + 3 条被规则读成开关的裸开关句，每条一次复核），算术对上说明复核既没漏也没多调；③**中位耗时 4.9 → 3.6 s**，不是模型变快，而是以前指令类不发模型请求、评测脚本要空等满 `--wait`（那 25 条每条 20 s），**产品侧的变化是相反的**：指令由瞬时变成约 3.6 s。另外新计数把老问题的性质说清楚了：那三条未通过的裸开关句（"打开""关了吧""那你开开呗"）**是真的改了风扇模式**，而复核拦不住——单独问模型同一句，它给的标签与规则完全一致（当日实测），正是 `Intent_Review_Proposal.md` 第 9 节说的"规则与模型一起判错"那一类，要修得靠规则层 |
| **指令的模型复核（2026-09-14，`Intent_Review_Proposal.md` 阶段一）** | 用户确认"可以接受，做吧"后实施。规则判出指令不再立即执行：先把同一句话交给模型独立判一次（`JOB_REVIEW`，与分类同一套提示词），两边一致才执行；不一致、或只有模型判成指令时改为反问、等用户点头（新增 `_AFFIRM_WORDS`/`_DENY_WORDS`，窗口 25 s，与指令反问同一口径）。**模型仍然没有执行权**：执行什么由规则的判定决定，数值仍从用户原话取，模型只能否决、不能发起。两处实现判断：①**补通道的回答跳过复核**——"温度"补的是上一条指令缺的一半，单独问模型必然答"在问当前温度"，每次补全都会被读成分歧；②**空回复按"模型不可用"照原样执行**——超时与连接断都表现为空回复，裁决表那一行写的是"与改动前一样"，一次超时不该把指令吃掉。实测（qwen3.5:4b）一致执行端到端 3.7~4.1 s，首次冷启动 10.1 s。补 7 项回归测试；`assistant_benchmark.py` 增"复核拦下/错误执行"两项计数。**阶段二（复核问题类）未做**，理由是问题答错无副作用而误报反问约 8/148 |
| **征询语气守卫（2026-09-14）** | 32 句鲁棒性实验暴露的最后一类会产生动作的误判：7 句征询语气里 5 句被执行（"风扇是不是该开了"真开了风扇）。它与命令在关键词层面同形，`_FAN_STATE_WORDS` 只认状态词（开着／在转），拦不住。新增 `_CONSULTATIVE_WORDS` 并在 `_fan_intent()` 中前置判定，落点选 `FAN_STATE` 是因为该档事实本就带通风阈值与当前读数，正是"要不要开"需要的两样东西。**"能不能"刻意不收**——`_FAN_ON_WORDS` 的注释里记着真实用户说过"能开风扇不"。误判方向偏向"当作提问"：读成提问用户再说一句就是了，读成命令风扇已经转了。补 3 项回归测试，`pytest` 990 全绿；32 句错误执行 5 → 0，留出题库逐项不变，87 句题库整库不含征询词故不受影响 |
| **用户实测查出两个问答 bug（2026-09-14）** | ①"今天天气不挺好的 咋地铁站这么热啊 现在是不是都快30度了"被答成"系统只保留本次运行以来的数据……当前温度为 25.9℃"：过去时段词表里的"今天"对**当前读数**也生效。拆成"严格指过去"（昨天、上周、今早……）与"包含现在"（今天、本周……）两组，当前读数只认前者，统计量照旧两者都认。②"我可以问你什么问题"被答成"温度现在是 26.3℃"：能力问法表只有"可以问什么"，多一个"你"就没命中，交给模型分类后，模型偶尔照着提示词第一个例子回 `current_value temperature`（接模型复现 5 轮中 1 轮，其余 4 轮答"没听懂"，同样不对）。补"问你什么、问你些什么、哪些问题、能回答什么"等整句说法，复查确认这类问句不再调用模型。**两处都不是当天前面的改动覆盖的**：②这类句子 09-09"占位答复"之前会直接回清单，那次改动之后才开始交给模型。各补 1 项回归测试；87 句基线仍 84/87，留出题库结果不变。数字本身两次都没有被用户的"快30度"带偏——改写时模型只看得到模板句，看不到原话 |
| **解释档放宽：测了不放（2026-09-09）** | 我推测温度降到 0.3 后解释档会便宜不少，**推测错了**：中位 3.5 s → 10.0 s，与 0.8 下的 3.7 s → 9.7 s 几乎一致。原因是把两件事混了——温度管采样随机性、不管输出长度；改写档快是因为不再画蛇添足少生成了 token，而解释档的长度由提示词定死（"两到三句"），低温没有东西可裁。当初的取舍因此在新参数下重新成立 |
| **出口检查的成本实测（2026-09-09）** | 用户质疑温度降到 0.3 后出口检查是否过度限制。逐项统计触发次数：**0.3 档 42 次调用零触发**，0.8 档 42 次拦下 4 次（凭空判断 2、长度上限 2，如"环境舒适宜人""这个数值需要引起注意"）。**结论不是删掉**：零触发意味着留着的成本为零、删掉的收益也为零，而删掉之后换模型或调回温度时假话直接出去。温度管发生率，检查管后果 |
| **采样温度定为 0.3（2026-09-09）** | `temperature` 此前未设，用的是 Ollama 默认 0.8。出口反复退回的补话（"请注意保暖"等）实测是**采样随机性**而非模型不懂：默认温度三批合计采纳 72/90，0.3 与 0.0 两批 60/60（p≈0.0005），低温还快约 5%。取 0.3 不取 0.0，是因为重写依赖第二次输出与第一次不同。**不改变任何保证**，只把出口检查从"日常在挡"退回"兜底" |
| **num_predict：测了不动（2026-09-09）** | 原以为收紧它能在生成阶段截住话痨。100 次实测四档全是 25/25、零截断、耗时无差——温度定下来后改写只用二三十 token。**且它有实伤**：与解释档共用客户端，解释档要 57 token，48 时会断在"…仍有 11.0℃"这种紧跟数字处。只测改写档会得出"48 安全"的错误结论 |
| **按需重写（2026-09-09）** | 用户问"能否牺牲反应时间让模型自校验一轮"。改为**确定性检查判失败后重写一次**，判官仍是代码——自校验由刚出错的那个模型当判官，且要给 100% 的请求付双倍时间。实测 30 次：首轮退回 5（17%），重写救回 4（80%），平均 1.8 s → 2.3 s。最有价值的一次救回：49.5 dB 对 80 dB 阈值却说"已经超出正常范围"，重写成了平铺直叙。只重写一次 |
| **解释档被长度上限误伤（2026-09-09）** | 加长度上限当天引入的回归：解释档的本职就是写长（把模板丢掉的九项事实讲出来），却与改写档共用 `choose()`，被自己的长度判死。**测试没抓到——没有任何用例拿真实长度的解释档输出走过 `choose()`**，靠一次手工核对发现。已加 `expanded` 开关并补测试 |
| **模板只在报警时表态（2026-09-09）** | "现在多少度"原先回"…，处于正常范围"——只问了读数却附赠一句判断。改为**报警说、正常不说**：越限是无论如何都要知道的事，"一切正常"可以由沉默表达 |
| **占位答复（2026-09-09）** | 规则落空时原先立刻甩出整张能力清单，几秒后被模型答案整段换掉，读起来像第一次答错了。改为先回"让我想想…"（`AnswerSource.PENDING`，只在模型确实接单时才用），模型也认不出时换成一句短的并把清单变成一个可问的问题。"你能干什么"仍直接给清单 |
| **出口再加两道（2026-09-09）** | 模板变短后模型反而更爱补话。30 次实测里补的分两类：纯废话（"请注意保暖"）与**无依据的判断**（"目前该区域已恢复正常"、49.5dB 说"水平较高"）。后者已有黑名单拦不住——它只管"未越限却称越限"。故加：模板没表态则改写不得表态（事实越限时不限）、建议类措辞按词拦、长度上限 1.4×+6 兜底。实测 30 例采纳 20 退回 10，退的全是这两类 |
| **"闹腾"词表缺口（2026-09-09）** | "这半天里最闹腾的时候"被答成**温度**最高值：闹腾不在噪声词表，通道落空后被记忆用上一轮的温度补位。记忆的护栏（只补给已匹配统计词的句子）在此无用——"最闹"正是统计词。词表缺口只能补词表 |
| **模型改写的实测（2026-09-09）** | 用户质疑"若模板能干完所有事，模型就没有存在必要"。据此实测 72 次调用（18 个事实已知的场景 × 4）：输出中含状态断言的 52 次**全部与事实相符**，接地校验 72/72 通过，平均 5.4 s。**因此撤回"读数类不送模型改写"的提议**——模型对现状的判断是可靠的。附带教训：第一版判定器把 6 次判成错误，实为"暂未发生越限"里否定词在断言词前 3 字、超出了我设的 2 字窗口，是**判定器的 bug 而非模型的**；差点据此得出 12% 错误率 |
| **余量按需附加（2026-09-09）** | 读数回答原先无条件缀上"距阈值还有 N"，函数文档自陈 answered without being asked。用户当初要的是"一句话两个要求"——问了两件才答两件，实现成了永远答两件。改为 `Intent.wants_margin`；余量仍照常计算并留在 Facts 里（解释档要用），管的只是那一句模板说不说 |
| **反问扩到指令（2026-09-09）** | 三条约束写死：只补对象不补数值（原话没有数值就照旧拒绝）、窗口 25 s 短于提问的 60 s、反问里回显原话。理由是挂起的若是指令，超时最坏结果是**系统状态被改**而非答非所问。同时修掉一处：答复必须是**裸的通道词**，原先只看意图种类，"现在噪声多少"会被吞成上一轮的答复并令指令反复反问 |
| **裸开关反问（2026-09-09）** | "那你开开呗""打开"没提风扇，规则落空。两种补法取反问而非话题记忆——记忆是悄悄猜，反问是明着问，代价同为一轮往返而只有后者可核对 |
| **跨时间问题（2026-09-09）** | "昨天最高多少"此前答成本次运行以来的最高值。**错误里最难发现的一种**：每个数字都是真的，接地校验尤其拦不住——错的不是数字而是它所属的区间。现加范围说明前缀，值照给 |
| **越下限措辞（2026-09-09）** | 湿度 27.1%RH 说成"已超出 30%RH 的报警阈值"，字面就错了，应为"已低于…报警下限"。双向阈值引入后该分支才有第二种可能，原实现两侧共用一句话 |
| **错别字归一化（2026-09-09）** | 「现在多少读」（度→读，拼音同音）整句落空。按**词组**而非单字建表——「读」若单字映射成「度」，为修一个错字会毁掉「读数」这个本系统天天用的词；表里每条左侧（多少读／阀值／燥音／分被）在中文中都不成词，改写因而无损。「阀值」不是手滑而是流传很广的误写，打字时理直气壮 |
| **检查脚本改为自动判定（2026-09-09）** | `check_doc_numbers.py` 原用手工维护的历史值黑名单，一天之内用例数走了 900→904→907→911，每次都要手工补一条、漏补则静默通过。改为：处在总数位置又不等于当前实测值的数字一律报，仅放行小于 400 的分项（分层最大 233）与「上位机部分」这个同样合法的总数。改完立刻多抓出六处，其中 `答辩问答准备.md` 一整张规模表停在 2026-09-07（650/610/74 个源文件） |
| **风扇指令词表放宽（2026-09-09）** | 真人试用中连说三句要开风扇（能开风扇不／那你开开呗／开风扇）全部失败——词表有"打开/开启/开一下/开起来"，唯独没有最短的"开"。**题库测不出**：`assistant_benchmark.py` 里四条开风扇例句每条都恰好含词表已有的词，题库与词表互为印证。现改为匹配裸的"开/关"，另加 `_FAN_STATE_WORDS` 前置守卫区分"风扇开着吗"（问）与"能开风扇吗"（令）；题库补入 9 条真实说法 |
| **拒绝手动播报（2026-09-09）** | 白名单仍是四项，新增 `ANNOUNCE_REQUEST` 只认出不执行。起因是"试一下语音播报能不能响"落到噪声通道（响/声音是噪声关键词），一条办不到的请求被答以真实声压级——与"帮我订张票被答成当前湿度"同类。播报要构造 `ALERT_*` 帧直驱硬件且不可撤回，故不进白名单 |
| **论文收尾压缩** | 计划里"第 5/6/7 章重复同一条理由"的诊断经检索**不成立**（该表述全文 0 次）；真正的重复只有两处——第 1 章 1.3 与 1.4 是同一份清单的两种写法、第 9 章 9.9 与第 10 章 10.3 逐条重复六项局限，均已合并。全文通改仅收回 1.4%，逐句压缩确已到下限，**口径遂放宽至 2.9 万字** |
| **论文规模数字订正** | 由第 7 章内部算术矛盾（"801+网关25=900"）查出表 7-1 六处过时：上位机由 88 文件/10600 行/801 用例改为 **83/11590/875**；service、application、ui、集成四行与表 6-3 一并回填，各列现已加得上 |
| 湿度双向阈值 | 规则表改为 `AlarmBand` 区间制，湿度 30~75 %RH。**温度两级门限评估后不做**——引入"严重程度"新维度要一路动到固件，属增强而非修缺陷 |
| 问答第一档：多轮指代 | 上一轮通道记忆，3 分钟超时；只补给已匹配到其它关键词的句子；指令永不继承通道 |
| 问答第二档：反问澄清 | 缺通道时问回去，60 秒有效；**反问与模型分类同时进行**，不是二选一 |
| 问答第三档：模型写接地解释 | 整张事实清单交给模型；范围窄到 `{ALARM_STATE, FAN_STATE}`，依据是中位耗时 3.7→9.7 s 的实测 |
| 报警断言黑名单 | `triggered` 不为真时不许说"超标/告警/故障"。**黑名单不完备，是缓解不是保证**，与数字白名单性质不同 |
| 移动端留痕 | PC 活动日志记「移动端下发：… → …」。**只留痕，不同步聊天记录** |
| LCD 第二页 | 命令码 0x16，下发"答案种类 + 数值"而非文本；**模型改写不影响屏幕**。~~源码已改、**未烧录**~~ → **2026-09-18 用户确认：已烧录，实机图已进论文** |

> **附注：关于"交互式"的边界（2026-09-08 讨论，第四档据此不做）**
>
> 一条不动的红线：**数字永远由检索层产出，模型不得直接说出任何读数、阈值或统计量**。
> 现有的接地校验（`numbers_are_grounded`）与"控制指令的数值由代码从用户原话正则提取"
> 两条机制都建立在这条线上，论文第 7 章的论证也是。交互性可以加，这条不能换。
>
> 四档由易到难：多轮指代 → 反问澄清 → 让模型写更长的接地解释 → 让模型选调用哪个检索。
> **前三档已做，第四档不做**：它改的是架构，收益只是"更像 agent"，而本文已有一条更硬的
> 叙事线（可靠、可验证、不会编数字），不必去换。真正的制约也不是模型能力，是
> **答辩现场的时延**：4B 纯 CPU，改写约 2~4 s、解释约 8~14 s，规则优先（现命中 86.2%）必须保留。

## 文档整治记录（2026-09-09）

本文件拆分之后，对全部 83 份 md 做了一次审计，修掉三类问题：

**与现状不一致**：`项目代码结构导览.md` 缺了 2026-09-07 之后新增的整层代码
（三个 dispatcher、`ventilation_controller`、`alarm_announcer`、`assistant/` 六个模块、
`llm` 包），已补齐并新增 §1.11；`Protocol_Design.md` 缺命令码 0x16，已补并**降级为同步副本**
（权威在 `manager.py` + 固件头文件，一致性由测试守护）；15 处过期数字已订正。

**职责重复**：`Runtime_Mode.md` 与 `Hardware_Simulation_Mode.md` 划清了"怎么跑"与"为什么"；
`Multi_Client_System_Architecture.md` 的接口细节交给 `PC_Android_接口设计.md`；
论文四份规划文档与 Skill 三处记录都加了状态横幅，指明谁是现行来源。

**职责过大**：`Assistant_Design.md` 927 行按同样手法拆成设计（493 行）+
[`status/问答实现记录.md`](status/问答实现记录.md)（469 行）。

**两份文档按用户决定重写**：`Test_Plan.md`（上一版写于编码开始前，通篇"用例将在开发完成后补充"）、
`Coding_Standards.md`（不含 ruff/mypy，且引用了从未存在的 `src/common/exceptions/`）。

**新增两个检查脚本**，已进收尾清单：

| 脚本 | 挡住什么 |
| --- | --- |
| `scripts/check_doc_numbers.py` | 文档里的测试数/源文件数过期。带"当时/曾/原为"的历史叙述自动豁免 |
| `scripts/check_doc_links.py` | markdown 坏链。拆分时 11 条 `../` 链接因目录深了一层全部失效，而坏链没有任何提示 |

### 第二轮：逐条核对文档说法与源码（2026-09-09）

第一轮只比对了"文档 vs 文档"和"文档 vs 数字"，遗漏了最要紧的一类——**文档说法 vs 源码事实**。
用户追问 `Skill_Audit_Report.md` 时暴露了这个缺口（它第 6 节自称"当前状态"，
列的却是 10 active / 4 archived，实际已是 12 / 5）。据此把当天新写的每一句可核对的话
拿回源码逐条验，查出 **6 处错**，其中 3 处是我当天自己写进去的：

| 位置 | 错在哪 | 实际 |
| --- | --- | --- |
| `Test_Plan.md`（当日新写） | 称"有专门用例断言 `ui` 不 import `device`" | **没有这种测试**。边界靠 `test_hardware_mode.py` 那类"真实对象栈能否跑通"固定 |
| `Test_Plan.md`（当日新写） | 称用 WSL2+socat 测 `SerialChannel` | 自动化测试用的是假串口 `_FakeSerialPort`；socat 是二阶段的一次性人工验证 |
| `项目代码结构导览.md`（当日新写） | 播报冷却"默认 60 s" | `DEFAULT_COOLDOWN_SECONDS = 30.0`，其余文档都写的 30 |
| `项目代码结构导览.md`（当日新写） | assistant"6 个模块" | 实际 8 个（漏了 `llm_port.py` 与 `assistant.py`） |
| `STM32F407_上板联调与测试手册.md` | 让人去看"每秒一次的心跳帧（`stm32_heartbeat`）" | **固件早已没有心跳**，改由采集周期每 3 秒上报数据。且读失败的通道不发帧，一个传感器都不接时串口上什么都没有 |
| `Skill_Audit_Report.md` | 第 6 节自称当前状态却是 8-11 的旧清单 | 已重写，并加进自动检查 |

另有 LCD 相关描述在三份文档里仍写着分页前的样子（34 字字库 / 三行布局），已同步。

**新增第三个检查脚本** `scripts/check_doc_identifiers.py`：把文档里反引号包着的类名、
常量、函数名拿去源码里找。它**不设退出码**——框架名、环境变量、板子丝印必然找不到，
需要人过目。首次运行就是靠它捞出上表的心跳与拼帧方法名两条。

三个文档检查脚本合起来覆盖的是三类不同的漂移：**数字**（`check_doc_numbers`）、
**链接**（`check_doc_links`）、**名字**（`check_doc_identifiers`）。

**一处未处理**：`firmware/.../Drivers/SYSTEM/usart/usart.h` 仍在磁盘上，
而 `硬件落地方案.md` 写的是 usart.c/.h 已移除。Keil 工程确实没有引用它（校验通过），
属残留文件而非文档错误，按"禁止删除已有文件"未动。

## 0. 速查：怎么跑起来 / 环境在哪

### 九个可运行入口（Windows 下双击即可）

| 双击 | 跑什么 | 需要硬件？ |
| --- | --- | --- |
| `run_gui_模拟数据界面.bat` | PyQt6 上位机界面，**模拟数据** | 否 |
| `run_gui_hardware_真实硬件界面.bat` | PyQt6 上位机界面，**真实 STM32**（会让你选串口） | 是 |
| `run_api_server_手机网关.bat` | Android 网关（会让你选模式，并打印手机要填的 IP） | 模拟模式否 / 硬件模式是 |
| `run_all_界面加网关.bat` | **界面 + 网关一起跑**，共用一条串口（硬件模式下两端同时看数据必须用它） | 模拟模式否 / 硬件模式是 |
| `collect_data_实验数据采集.bat` | **论文实验数据采集**（交互选实验类型与串口，输出 CSV + 可直接粘贴的统计表格） | 是 |
| `start_llm_启动本地模型.bat` | 拉起本地 Ollama 并**预热**模型（演示前跑，冷启动首问约 8.8 s） | 否 |
| `stop_llm_停止本地模型.bat` | 卸载模型释放约 3 GB 内存；`--server` 连服务一起停 | 否 |
| `cloud_sync_导出并上传.bat` | **导出整点归档并上传 OSS**（2026-09-17 新增；`--no-upload` 只导出不上传，现场没网时用它） | 否 |
| `cloud_view_查看云端.bat` | **只读**查看云上已有文件并打开控制台（2026-09-17 新增；不上传、不删除、不改动任何东西） | 否 |

命令行等价写法见 `docs/05_Test/Runtime_Mode.md`。
**浏览器控制台**（2026-09-23）不是新的 `.bat`：网关启动后打开 `http://127.0.0.1:8000/web/`；没有板子时用 `python scripts/run_api_server.py --mode virtual --inject-faults`；或直接双击 `web/index.html` 看回放。见 [`web/README.md`](../../web/README.md)。
（2026-09-18 核对：本表曾停在七个，漏了 09-17 新增的两个上云入口。）

### 质量基线（每个任务收尾前应全绿）

```bash
QT_QPA_PLATFORM=offscreen pytest    # 1348 passed（2026-09-23）
ruff check src tests scripts        # All checks passed!
mypy src                            # 99 source files, no issues
```

### 本机已装好的工具链（2026-08-15 安装，换机器需重装）

| 工具 | 位置 / 版本 |
| --- | --- |
| JDK 17 | `C:\Program Files\Eclipse Adoptium\jdk-17.0.20.8-hotspot` |
| Android SDK | `D:\android-sdk`（platform-34 / build-tools 34.0.0 / platform-tools） |
| Gradle 8.7 | `D:\android-sdk\gradle\gradle-8.7`（工程另带 `gradlew` wrapper，一般用 wrapper 即可） |
| Android Studio | `C:\Program Files\Android\Android Studio`（2026.1.3，自带 JBR） |
| Keil MDK + ARM Compiler 5.06 | 用于 `firmware/stm32f407/`，用户本机已有 |
| `oss2` 2.19.1（阿里云 OSS SDK） | **2026-09-16 经用户授权安装，装在 D 盘**：`pip install --target D:\PyPkgs oss2`，连同 14 个依赖共 26.8 MB；C 盘 site-packages 里放了一个 `_dpkgs.pth` 把该目录加进搜索路径。**装 D 盘的原因与 Ollama 同**——C 盘仅剩 35.8 GB。⚠️ `cryptography` 存在双版本：C 盘 49.0.0（2026-07-25 由其它包带入）遮蔽了 D 盘的 50.0.1，因为 `.pth` 路径排在 C 盘之后；已冒烟验证 `oss2.Auth`/`Bucket.sign_url` 正常，暂不处理。**尚未写入 `pyproject.toml`**，等上云功能实现时再声明 |

> 注意：Android Studio 首次打开 `android/` 时会把 `android/local.properties` 的 `sdk.dir`
> 改写成它自己下载的 SDK 路径，这是正常的，不影响构建。

### 顶层目录速览

```
src/          Python 上位机（10 个包：core/device/protocol/communication/service/
              application/api/ui/gateway/llm；ui 与 gateway 是平级的两个呈现端，
              llm 是本地语言模型服务的适配层）
scripts/      启动入口与验证工具（run_gui / run_api_server / virtual_stm32 等）
tests/        1315 个测试，结构与 src/ 对应
firmware/     STM32F407 固件（Keil 工程，独立工具链）
android/      Android 客户端（Kotlin + Gradle 工程，独立工具链）
docs/         01~10 号文档目录，本文件在 05_Test/
```

---


## 1. 项目定位

### 1.1 当前项目是什么

一个**面向嵌入式设备的通用上位机开发平台**（Python + PyQt6），用于与 STM32 等 MCU 通过 UART/USB/TCP/蓝牙通信，实现设备调试、监控与数据可视化。项目定位见根目录 `CLAUDE.md` 与 `docs/01_Project/Project_Overview.md`：架构与代码仍保持通用性，**不是**针对某一具体设备硬编码的一次性工具；本科毕设的**实际验证路线已收敛**（2026-08-14）为 STM32F407ZGT6（正点原子探索者V3）+ AHT20 温湿度传感器（ATK-MB016）+ HH_07.06 噪声传感器（Modbus RTU），应用场景为地铁站公共空间环境监测，论文叙事以通信协议设计与可靠性验证为主线（详见 `docs/01_Project/Project_Overview.md`"毕设应用场景与选题定位"一节）。STM32 侧固件（`firmware/stm32f407/`）第一版正式固件已完成软件实现并通过 Keil 编译（0 Error/0 Warning），详见本文档新增的"STM32 Firmware"一节与 `docs/09_STM32Hardware/`。

### 1.2 当前采用的整体架构

`docs/02_Architecture/System_Architecture.md` 定义的五层架构，落地为如下 `src/` 目录（实际实现比原始五层文档更细，新增了 `application`/`api` 两层作为桥接）：

```
core           跨层基础设施（异常、时间戳、ID 类型别名）
device         Device 抽象（SimulatorDevice / RemoteDevice / sensors 预设）
protocol       通用帧协议编解码（帧头/设备ID/命令类型/长度/Payload/CRC）
communication  通信介质抽象（LoopbackChannel / SerialChannel）
service        Service Layer（DataService/ControlService 及实现、SensorDataProcessor）
application    组合根/运行时桥接（DeviceManager、ApplicationRuntime、HardwareDeviceReceiver）
api            对外统一门面（ApiInterface / LocalApi）
ui             PyQt6 界面（MVC：controller.py + main_window.py + widgets/）
```

### 1.3 通用框架 + 具体验证场景的设计思想

项目采用"两条腿走路"的验证策略，在 `docs/05_Test/Hardware_Simulation_Mode.md` 中有完整说明：

- **通用框架层**（`core`/`device`/`protocol`/`communication`/`service`/`application`/`api`/`ui`）：不绑定任何具体设备型号、传感器或业务语义，`Frame`/`DeviceInterface`/`CommunicationChannel` 等抽象接口是设备无关的
- **具体验证场景**（`device/sensors/` + `service/sensor_data_processor.py`）：在通用框架之上，构建了一个"温度/湿度/噪音环境监测"的具体应用场景，用于在真实硬件到位前，验证整条数据链路（生成→协议→传输→分发→统计→报警→界面展示）在贴近真实业务的情况下是否可用
- 这一设计使得：即使最终毕设方向调整，通用框架部分基本不需要重写；即使传感器种类变化，也只需要在 `device/sensors/` 下新增预设，不影响其余七层

---


## 2. 当前已完成模块

### Core Layer

- **已实现文件**：`src/core/__init__.py`、`exceptions.py`、`models.py`、`timestamps.py`
- **核心功能**：`PlatformError` 异常基类及 `ValidationError`/`StateTransitionError`/`NotFoundError`/`OperationTimeoutError`；`DeviceId`/`ClientId`/`ChannelId`/`CommandType` 四个 `str` 类型别名；`now_utc()`/`to_iso8601()`/`from_iso8601()`/`monotonic_ms()` 时间戳工具（强制时区感知）
- **测试状态**：`tests/core/` 3 个文件，13 个用例，全部通过

### Device Layer

- **已实现文件**：`src/device/__init__.py`、`capability.py`、`interface.py`、`metadata.py`、`model.py`、`remote.py`、`simulator.py`、`state.py`，以及子包 `src/device/sensors/`（见下方"Sensor Simulation Layer"）
- **核心功能**：
  - `DeviceInterface`（Protocol）：`device_id`/`capability`/`status` 结构化契约
  - `Device`：通用不可变设备模型
  - `DeviceCapability`/`ConnectionState`/`OccupancyState`/`DeviceStatus`/`DeviceMetadata`：能力描述与状态模型
  - `SimulatorDevice`（Simulator 模式）：基于 `ValueGenerator`（常量/序列/随机/平滑游走/带峰值噪声）主动生成数据
  - `RemoteDevice`（Hardware 模式）：只维护 `device_id`/`capability`/`status`，不生成数据、不依赖 `communication`
- **测试状态**：`tests/device/` 6 个文件 44 个用例 + `tests/device/sensors/` 4 个文件 32 个用例，共 **76 个用例**（10 个文件），全部通过

### Protocol Layer

- **已实现文件**：`src/protocol/__init__.py`、`decoder.py`、`encoder.py`、`exceptions.py`、`frame.py`
- **核心功能**：`Frame`（device_id/command_type/payload 结构化消息）；`encode()`/`decode()` 实现帧头 `0xAA 0x55` + 1 字节 device_id + 1 字节 command_type + 2 字节大端 length + payload + 4 字节 CRC-32（`zlib.crc32`）；`ProtocolError` 及子类（`FrameValueError`/`FrameSyncError`/`FrameLengthError`/`ChecksumError`）
- **测试状态**：`tests/protocol/` 3 个文件，28 个用例，全部通过

### Communication Layer

- **已实现文件**：`src/communication/__init__.py`、`exceptions.py`、`interface.py`、`loopback.py`、`serial.py`
- **核心功能**：`CommunicationChannel`（ABC）：`connect`/`disconnect`/`send`/`receive`/`is_connected`；`LoopbackChannel`：内存回环实现；`SerialChannel`：基于 `pyserial` 的真实串口实现，含 `SerialPortNotFoundError`/`SerialConnectionError`/`SerialReadTimeoutError`/`SerialWriteError` 异常转译
- **测试状态**：`tests/communication/` 3 个文件，40 个用例（含 mock pyserial 的虚拟串口测试），全部通过

### Service Layer

- **已实现文件**：`src/service/__init__.py`、`command_models.py`、`control_service.py`、`control_service_impl.py`、`data_models.py`、`data_service.py`、`data_service_impl.py`、`sensor_data_processor.py`
- **核心功能**：`DataPoint`/`Command`/`CommandResult`/`CommandStatus` 数据与指令模型；`DataService`/`ControlService` 抽象接口 + `InMemoryDataService`/`InMemoryControlService` 实现（"共享读、独占写"占用规则）；`SensorDataProcessor`（见下方"Sensor Simulation Layer"，2026-08-12 新增 `on_status`/`ThresholdStatus` 与 `on_statistics`/`StatisticsCallback`）
- **测试状态**：`tests/service/` 13 个文件，**275 个用例**，全部通过（2026-09-09 实测；其中 `assistant/` 子包 164、`test_sensor_data_processor.py` 40、`test_ventilation_controller.py` 26、`test_alarm_announcer.py` 22）

### Application Layer

- **已实现文件**：`src/application/__init__.py`、`manager.py`、`runtime.py`、`hardware_runtime.py`、`hardware_runner.py`、`frame_stream.py`（2026-08-12 新增）
- **核心功能**：
  - `DeviceManager`：设备注册（同时支持 `SimulatorDevice`/`RemoteDevice`）、device_id(str)↔Frame.device_id(int) 映射、上/下行帧编解码、`CommandTransport` 契约实现
  - `ApplicationRuntime`：组合 `DeviceManager`+`InMemoryDataService`+`InMemoryControlService`+`SensorDataProcessor`（内部持有，`_alarm_processor`，现在同时服务报警与统计两个用途）的门面；`register_device()` 会自动调用新增的 `watch_alarms_for(device)`，按 `device.capability.channels` 把设备接入报警评估（统计评估共用同一条订阅，见 `subscribe_statistics()`）
  - `HardwareDeviceReceiver`：Hardware 模式数据接收链路——`channel.receive()` → `protocol.decode()` → 过滤 `DATA_REPORT` 帧 → 转 `DataPoint` → `DataService.publish()`；独立于 `DeviceManager` 注册表，`wire_id` 由调用方直接指定
  - `HardwareRuntimeRunner`：包一层 `start()`/`stop()`/`running`/`run_once()` 状态管理在 `HardwareDeviceReceiver` 外面；**不启线程、不用 asyncio、自身不循环**，"持续运行"由外部驱动方（`scripts/run_gui.py` 里的 `QTimer.timeout.connect(runner.run_once)`）负责；`run_once()` 内部 `try/except Exception` 兜底，任何底层异常都不会污染 `running` 状态或向上传播
  - **`HardwareDeviceReceiver` 字节流拼帧修复（2026-08-12，硬件在环演示中发现的真实 bug）**：`poll_once()`/`poll_until_empty()` 原先直接把每次 `channel.receive()` 的返回值整体丢给 `decode()`，隐含假设"一次 `receive()` 恰好是一帧"——这个假设只对 `LoopbackChannel`（`send()`/`receive()` 按 deque 一对一保留消息边界）成立。真实字节流传输（`SerialChannel`）没有消息边界：`scripts/virtual_stm32.py` 连续发送 3 帧之间无延时，一次 `receive()` 经常读到多帧粘连的字节；或反过来一帧被拆成两次 `receive()`。两种情况原先都会让 `decode()` 抛 `FrameLengthError`，被 `HardwareRuntimeRunner.run_once()` 的兜底吞掉，界面表现为"订阅成功但永远没有数据"且没有任何报错提示。修复方式：`HardwareDeviceReceiver` 新增内部 `_buffer: bytearray`，`_next_frame()`/`_extract_buffered_frame()` 按帧头（`HEADER`）+ 声明长度（`LENGTH_SIZE`）从累积字节中精确切出恰好一帧，不足则等待下一次 `receive()`；`_resync_buffer()` 处理缓冲区开头不是合法帧头的脏字节（丢弃并计入 `error_count`，避免永久卡死）。只改了 `application/hardware_runtime.py`，未触碰 `protocol`/`communication` 任何接口（**注：这两个方法名是 2026-08-12 当时的**；后来这段拼帧逻辑被抽成独立的 `application/frame_stream.py::FrameStreamBuffer`，现在按 `feed()`/`extract_frame()`/`_resync()` 组织，按旧名字去源码里找会找不到）——`decode()` 自己的 docstring 早已声明"在任意字节流中定位帧边界"不是它的职责，属于调用方（本模块）该做的事
  - **`DeviceManager.deliver()` Hardware 模式命令下发修复（2026-08-12，硬件在环演示中发现的第二个真实 bug）**：原实现无论 Simulator 还是 Hardware 设备都走同一套"发送后本地立即自问自答"逻辑（`registration.channel.send(request)` 后紧接着本地 `receive()`/构造 ack/再 `receive()`），只对 `LoopbackChannel` 成立；对真实 `SerialChannel` 时，`virtual_stm32.py`（或未来真实固件）不会瞬间自动应答，`receive()` 立即读到空字节，`decode()` 抛未捕获的 `FrameLengthError`，直接崩溃整个 GUI 进程。修复：`deliver()` 现在按 `registration.device` 是否为 `_DataGeneratingDevice`（即是否为 `SimulatorDevice`）分两条路径——Simulator 设备保留原有自环模拟逻辑不变（`_simulate_device_ack`）；Hardware 设备（`RemoteDevice`）改为 `_await_device_ack`：真正等待设备侧发回的 `COMMAND_ACK_CODE` 帧，用 `FrameStreamBuffer` 正确处理字节流粘连/半帧，带 2 秒超时（`_COMMAND_ACK_TIMEOUT_SECONDS`），超时抛 `core.exceptions.OperationTimeoutError`，经 `api/local_api.py` 转译为新增的 `api.exceptions.CommandDeliveryError`（`ApiError` 子类），`ui/controller.py` 已有的 `except ApiError` 兜底会把它转成界面上的错误提示而不是崩溃，`ui/` 本身零改动。等待期间收到但不是 ack 的帧（最常见是与命令同时到达的 `DATA_REPORT` 帧）会被跳过丢弃，不转发给 `HardwareDeviceReceiver`——这是刻意接受的 phase-1 折中（命令往返期间最多丢一条传感器读数），换来不需要在 `DeviceManager` 和 `HardwareDeviceReceiver` 之间共享一个接收循环。同步修改了 `scripts/virtual_stm32.py`：在每轮发送 3 条数据帧之间，新增 `_drain_and_ack_commands()` 监听并应答收到的命令帧（接受任意命令类型，因为这个脚本没有 `accepted_commands` 概念，真实固件应自行决定接受/拒绝），这样"发送命令"在硬件在环演示里才是真正端到端可用，不只是不崩溃
  - **`watch_alarms_for()` 在 Hardware 模式下漏调用的 bug（2026-08-12，接入阈值报警 UI 时发现的第三个真实 bug）**：`scripts/run_gui.py` 的 `build_hardware_runtime()` 因为要拿到 `DeviceRegistration.wire_id`，绕开 `ApplicationRuntime.register_device()`（facade）直接调用 `runtime.devices.register(...)`（`DeviceManager` 自己的方法）——这个绕开在早期就是刻意的、有文档说明的设计（见该函数自身 docstring），但这次新加的报警自动订阅逻辑只放进了 `register_device()` 里，没意识到 Hardware 路径根本不走这个方法，导致 Hardware 模式下报警从未被评估过（Simulator 模式一切正常，WSL 硬件在环演示时才发现"温度早就超过阈值但界面毫无反应"）。修复：把订阅逻辑拆成独立的公开方法 `watch_alarms_for(device)`，`register_device()` 内部调用它，`build_hardware_runtime()` 也显式调用它一次。**教训**：任何"设备注册后要做的事"，都必须同时检查 `ApplicationRuntime.register_device()` 和 `scripts/run_gui.py::build_hardware_runtime()` 两处——后者不是前者的简单包装，是刻意绕开的另一条路径
  - **`subscribe_statistics()`（2026-08-12 新增，统计信息 UI 接入）**：复用 `watch_alarms_for()` 已建立的自动订阅（`SensorDataProcessor.handle_data_point()` 本来就在维护统计，本次只是多加了一步 `on_statistics` 回调），因此 Hardware 模式**这次不需要额外修复**——上一条 bug 的教训被应用上了，实现前就确认过 `build_hardware_runtime()` 这条路径同样覆盖，WSL 硬件在环环境里也一并验证过
- **测试状态**：`tests/application/test_hardware_runtime.py` 15 用例（12 原有 + 3 条针对拼帧/断帧/脏字节重同步的新用例：`test_poll_until_empty_splits_several_frames_from_one_concatenated_chunk`/`test_poll_once_buffers_a_frame_split_across_two_receive_calls`/`test_stray_bytes_before_a_frame_are_discarded_and_counted_as_error`，均使用新增的 `_StreamChannel` 测试替身——它和 `LoopbackChannel` 的区别正是"不保留消息边界"，因此能真实复现这个 bug）+ `tests/application/test_hardware_runner.py` 22 用例 + `tests/integration/` 4 个文件 30 个用例（新增 `test_control_pipeline_times_out_for_remote_device_with_no_answer`，验证 `RemoteDevice` 收不到应答时优雅超时而不是挂死/崩溃；另外两条既有的 `..._for_remote_device` 用例改为用 `_seed_ack()` 显式模拟设备侧应答，反映 `deliver()` 修复后 `RemoteDevice` 真的需要一个应答者，`LoopbackChannel` 不再自动帮它自问自答）+ `tests/scripts/test_run_gui.py` 新增 `test_hardware_mode_device_channels_are_watched_for_alarms`（`watch_alarms_for()` 漏调用 bug 的回归测试），全部通过

### API Layer

- **已实现文件**：`src/api/__init__.py`、`exceptions.py`、`interface.py`、`local_api.py`
- **核心功能**：`ApiInterface`（抽象门面：`list_devices`/`get_device_status`/`subscribe_data`/`unsubscribe_data`/`acquire_control`/`release_control`/`submit_command`/`get_command_result`/`subscribe_alarm_status`/`subscribe_statistics`——后两个 2026-08-12 新增，均为纯新增方法、不改任何已有签名）；`LocalApi`（本地直连实现，委托 `ApplicationRuntime` 并转译异常为 `DeviceNotFoundError`/`CommandNotFoundError`/`CommandAuthorityError`/`CommandDeliveryError`）
- **测试状态**：`tests/api/` 2 个文件，**30 个用例**（`test_interface.py` 2 + `test_local_api.py` 28），全部通过

### UI Layer

- **已实现文件**：`src/ui/__init__.py`、`controller.py`、`main_window.py`、`theme.py`、`channel_display.py`（2026-08-13 新增，UI 展示层 channel→中文名/单位映射）、`widgets/__init__.py`、`widgets/chart_widget.py`、`widgets/control_panel.py`、`widgets/data_panel.py`、`widgets/device_panel.py`、`widgets/statistics_panel.py`、`widgets/top_bar.py`、`widgets/metric_card.py`、`widgets/status_banner.py`、`widgets/device_list_item.py`、`widgets/background_widget.py`（2026-08-13 新增，背景图像+半透明遮罩绘制层，见下方"GUI 背景视觉层"）；资源文件 `src/ui/assets/background.png`（用户提供的个性化背景图，不参与任何业务逻辑）；启动入口 `scripts/run_gui.py`（支持 `--mode simulator|hardware`）+ 根目录 `run_gui_模拟数据界面.bat`（转发参数）
- **核心功能**：MVC 架构——`MainController`（唯一 import `api` 的文件，转换为 Qt 信号）+ `MainWindow`（工业监控仪表盘布局，见下方"产品级视觉重构"）。**界面文字已全部汉化**
- **控制面板"命令类型"已从 `QLineEdit` 改为 `QComboBox`**：固定 6 个选项（PING/RESET/CONFIG_GET/CONFIG_SET/FW_UPDATE/CUSTOM，显示文本与实际发送字符串通过 `QComboBox` 的 `userData` 分离），默认选中 PING；选择 CUSTOM 时旁边的自定义命令 `QLineEdit` 才启用，切走则禁用并清空；`send_command_clicked` 信号仍然只发出一个 `str`，`MainController`/`ApiInterface` 调用链**零改动**
- **控制面板"通道 ID 订阅"已从 `QLineEdit` 改为可编辑 `QComboBox`**（最近一次改动）：预置 `temperature`/`humidity`/`noise` 三个常用通道名（仅为当前传感器验证场景的便利建议项，未绑定任何 channel 枚举，`ui/` 也未 import `device/sensors/channels.py`），下拉选择或直接输入自定义通道名均可；`_emit_subscribe` 改读 `currentText()`，`subscribe_clicked` 信号仍只发出一个 `str`，`MainController`/`ApiInterface` 调用链**零改动**
- **已验证 Simulator/Hardware 双模式下 `ui/` 零代码差异**：`SerialChannel`/`HardwareDeviceReceiver`/`HardwareRuntimeRunner`/`RemoteDevice` 全部只出现在 `scripts/run_gui.py` 里，`ui/` 目录下 0 处 import（已用 grep 反复核实）
- **阈值报警呈现（2026-08-12 新增）**：`MainController` 新增 `alarm_status_changed` 信号（`__init__` 时调用一次 `api.subscribe_alarm_status`，全局、非按设备/通道），`main_window.py` 收到后：`ControlPanelWidget.show_alarm()` 在活动日志追加红色文字条目（只在 `triggered=True` 时记，避免刷屏）；`DataPanelWidget.set_alarm()` 把对应行标红/清除背景色（`triggered` 直接驱动 True/False，不依赖两个信号谁先到达，因此能在恢复正常后自动清除颜色，不需要额外的"复位"事件）
- **统计信息呈现（2026-08-12 新增）**：`MainController` 新增 `statistics_changed` 信号（`__init__` 时调用一次 `api.subscribe_statistics`，同样全局），`main_window.py` 收到后调用新增独立 widget `StatisticsPanelWidget.update_statistics()`——刻意做成与实时数据表格分开的独立表格（不是在原表格里加列），列为 设备/通道/当前值/最小值/最大值/平均值/样本数，按 (device_id, channel) 逐行更新，不限于 temperature/humidity/noise（任何数值通道都会显示）
- **清空历史记录（2026-08-12 新增）**：`DataPanelWidget` 新增"清空历史记录"按钮 + `clear_history()` 方法，只清 `_history_list`，不影响实时数据表格/统计面板。纯前端本地状态，不发信号给 `MainController`、不涉及 `api`/`service`——没有什么需要后端"忘记"的东西
- **暂停接收（2026-08-12 新增）**：`ControlPanelWidget` 新增"暂停接收"按钮 + `unsubscribe_clicked` 信号，`main_window.py` 收到后调用已有的 `MainController.unsubscribe()`（真正调用 `ApiInterface.unsubscribe_data`，不是仅暂停 UI 刷新）。**注意边界**：只暂停该 (device_id, channel) 的实时数据表格/历史记录/曲线；`统计信息面板`/报警评估走的是 `subscribe_alarm_status`/`subscribe_statistics` 两个全局订阅（设备注册时就建立，见 `watch_alarms_for`），不受这里的暂停/取消订阅影响——这是刻意设计（"报警应该在任何人查看之前就已经在评估"），用户确认过要维持这个行为，不需要额外做"冻结统计面板显示"的机制
- **界面整体美化（2026-08-13，第一步：QSS 主题）**：`ui/theme.py` 定义一套深色卡片式工业监控风格 QSS 样式表 + 匹配的 `QPalette`，`scripts/run_gui.py` 的 `main()` 在构造 `QApplication` 后立即调用 `apply_theme(app)` 整体应用（符合 `pyqt6-ui-development-rules` skill Iron Law 3）。两个技术细节：(1) `QComboBox::drop-down` 一旦被自定义样式却不提供箭头图片，Qt 会直接不绘制下拉箭头——已避免这个坑；(2) `ChartWidget` 的背景/边框色通过 `self.palette()` 动态取值而非硬编码，因此单靠 `setStyleSheet()` 不够，`apply_theme()` 同时设置了 `QPalette`
- **产品级视觉重构（2026-08-13，第二步：仪表盘布局）**：在第一步纯主题的基础上，把布局从"多个 GroupBox 平铺"改为四层工业监控 Dashboard：
  - 顶部 `TopBarWidget`：标题/当前设备/连接指示灯/运行模式/时钟。运行模式是 `scripts/run_gui.py` 传入 `MainWindow(controller, mode_label=...)` 的纯展示字符串（新增可选构造参数，默认值保证旧调用点不变）——`ui/` 依然不知道 Hardware 模式底层怎么接线，只是显示一个调用方给的标签
  - 第一层 `MetricCardWidget` × 3（温度/湿度/噪声）：当前值+单位+趋势箭头（↑/↓/—，卡片自己比较上一次的值，纯展示计算）+ 阈值状态边框（复用 `alarm_status_changed`）
  - 第二层：`ChartWidget` 放大为主视觉区域，新增网格线、坐标轴数值、图例（含每条曲线当前值）——`chart_widget.py` 改动只涉及绘图，公开接口（`add_point`/`clear`/`series_names`）不变，9 个既有测试全部原样通过；线条颜色从原来的通用调色板改为跟随 `ui/theme.py` 的主强调色（青绿）+ 次强调色（蓝/紫），同层导入，不算跨层依赖
  - 第三层：`DataPanelWidget.realtime_group()` + `StatisticsPanelWidget`
  - 第四层：独立的 `StatusBannerWidget`（正常/警告/报警三态——警告来自 `error_occurred`，报警来自 `alarm_status_changed`，均为已有信号，未新增业务概念）+ `DataPanelWidget.history_group()`（历史记录从 `QListWidget` 改为 5 列表格：接收时间/设备/通道/数值/状态；"状态"列读取本 widget 内部按 `set_alarm()` 维护的 `_alarm_state` 字典，不涉及 service/api）+ 视觉弱化、不占主要空间的 `ControlPanelWidget`（未修改，仅布局位置变化）
  - 设备列表刻意保持底层是原生 `QListWidget`（`currentTextChanged`/`item(i).text()`/`setCurrentRow()` 等行为完全不变），只是通过 `setItemWidget()` 给每一行叠加 `DeviceListItemWidget`（设备 id + 在线指示灯 + 占用状态）做卡片式渲染——这个技巧让"设备列表→设备卡片"的视觉需求在零测试改动的前提下完成
  - `DataPanelWidget` 新增 `realtime_group()`/`history_group()` 两个访问器，返回内部两个 `QGroupBox` 供 `MainWindow` 分别放进不同层——`add_data_point`/`set_alarm`/`clear_history`/`row_count`/`history_count`/`_latest_table`/`_clear_history_button` 等全部既有公开方法/属性一个未改
- **信息层级与空间布局优化（2026-08-13，第三步：紧接产品级视觉重构之后同一天）**：不是重新设计，是在已完成的深色工业风格/四层布局方向上重新分配空间权重——"数据是主角，控制是辅助，日志是辅助"：
  - 新增 `src/ui/channel_display.py`：`channel_label()`/`channel_unit()` 两个函数，是 `温度/湿度/噪声`、`°C/%/dB` 这类展示文本唯一的权威来源，之前散落在 `control_panel.py`（预置下拉项）和 `main_window.py`（`_METRIC_CHANNELS`）里各自维护的写法，改为都从这里读，避免三处定义互相漂移；这仍然是 UI 展示层约定，未进入 `protocol`/`communication`
  - `DataPanelWidget` 实时数据表从 3 列（设备/通道/最新值）扩到 5 列（+单位+状态，单位/状态均来自 UI 层已有信息——`channel_unit()` 与 `set_alarm()` 已维护的 `_alarm_state`，不查询新的后端接口）；`QTableWidget#realtimeDataTable` 专属 QSS 规则把字号提到 12pt、单元格 padding 加大；`verticalHeader().setDefaultSectionSize(34)` 加大行高；`QGroupBox.setMinimumHeight(170)` 硬保证 temperature/humidity/noise 三行 + 表头无需滚动即可看全，不依赖布局挤压的运气
  - `StatisticsPanelWidget` 内部实现从"一行塞 7 列"的 `QTableWidget` 改为每 (device_id, channel) 一张 `_StatCard`（当前值 17pt 加粗最突出，最小/最大/平均一行方便横向比较，样本数小字），套在 `QScrollArea` 里以支持未来设备/通道数增多；**`update_statistics()`/`row_count()` 两个公开方法签名完全不变**，`MainController.statistics_changed` 的连线零改动
  - `DevicePanelWidget` 把"当前 ApiInterface 未提供该信息（DeviceStatusView 未包含能力字段）"这种暴露内部类型名的调试文字，改成面向最终用户的"未获取"；新增连接状态指示灯（复用 `top_bar.py`/`device_list_item.py` 已有的小圆点样式）
  - `MetricCardWidget` 的趋势箭头（↑/↓/—）从"上升=红、下降=青绿"改成三态统一的低调深色（`ui/theme.py` 的 `[cls="trend-*"]` 规则），理由：方向不等于好坏，红色应该只留给报警，避免"温度上升"这种正常现象被误读成警示
  - `MainWindow._build_dashboard_column()` 把"实时数据+统计信息"这一行的纵向 stretch 从 1 提到 3（与曲线的 3 打平，二者同为最高优先级），"报警/历史/控制"行相对总权重从 1/5 降到 1/7，自动被压缩，不需要单独再调 `ControlPanelWidget`/历史表格的内部代码
- **GUI 背景视觉层（2026-08-13～2026-08-14，第四步：紧接信息层级优化之后）**：详细过程见文件顶部"最近一次更新"一节，此处只记要点。第一版（背景层 + 全不透明面板）与第二版（面板半透明分层化）均已完成，第二版是用户实际看到运行效果后要求的重做，最终效果已获用户人工确认"符合预期"：
  - `BackgroundWidget`（新组件）：`cover_source_rect()` 纯函数计算裁剪矩形（保证背景图不变形、铺满窗口），`paintEvent()` 依次绘制背景图 + 半透明遮罩（`BACKGROUND_OVERLAY_OPACITY`，最终值 0.16），作为 `MainWindow` 的 `central` widget，其余所有子控件的 `QLayout` 都建在它上面
  - `ui/theme.py` 新增 `_rgba(hex, alpha)` 辅助函数与按面板类型分档的透明度常量，`QGroupBox`/`QFrame#*`/`QTableWidget`/`QListWidget` 等面板的 QSS `background-color` 全部从不透明十六进制色改为 `rgba(...)`，分档原则："一般信息面板最透明 → 实时数据表格/历史记录 → 统计信息 → 实时曲线/顶部卡片/控制面板 → 活动日志最不透明"，不是所有面板统一一个透明度
  - `ChartWidget._draw()` 的绘图区背景改为半透明填充（新增公开常量 `CHART_PLOT_BACKGROUND_ALPHA`），与 `chartCard` 外层卡片的半透明背景配合，避免图表区域变成"背景里挖出的一块不透明黑框"
  - `StatisticsPanelWidget` 内部 `QScrollArea` 的 viewport 需要额外 `setStyleSheet("background: transparent;")`——Qt 默认会给 `QScrollArea` 的 viewport 一层不透明背景，仅靠 QSS 选中 `QScrollArea` 本身不够
  - 交互控件（`QPushButton`/`QLineEdit`/`QComboBox`）保持原有不透明样式未改动，只有"信息展示类"面板参与半透明化
  - **背景图更换（2026-08-17）**：用户提供新图后替换 `src/ui/assets/background.png`（1920×1182，2.2 MB）。**零代码改动**——`theme.py` 的 `BACKGROUND_IMAGE` 常量指向的就是该文件名，全项目只有 `background_widget.py` 一处读它，无任何硬编码路径。旧图保留为 `background_v1.png`（未删除，可随时换回）。新旧两图宽高比同为 1.625，`cover` 裁剪方式不变；实测新图整体亮度略低（0.459 vs 0.499），故 `BACKGROUND_OVERLAY_OPACITY` 维持 0.16 未调
  - `data_panel.py`/`statistics_panel.py`/`control_panel.py` 各自的 `QGroupBox`/`QListWidget` 新增 `setObjectName()`（如 `realtimeGroup`/`historyGroup`/`statisticsGroup`/`controlGroup`/`activityLog`），供 `theme.py` 的分档 QSS 规则按 objectName 精确命中，不依赖控件在布局中的顺序
- **仪表盘重新布局（2026-08-18，为论文截图而做的一轮，同时修掉两个真实 bug）**：
  - **实时曲线由"三序列共用一个 Y 轴"改为"三格并排、各自量程"**。原实现在 `_draw()` 里把三条序列汇总取 min/max，于是温度(20~30℃)、湿度(60~90%)、噪声(40~110dB) 被塞进同一个 20~110 的轴——轴上的数字没有单位（三种量纲不可能共用一个线性轴），且温度 6℃ 的真实变化只占纵向 7%，画出来是一条直线。改为**横向**并排而非上下堆叠，依据是绘图区本身已是约 5.8:1 的扁条，竖切后每格约 17:1（一条缝，怎么缩放都是平线），横切后每格约 2:1；且每格正好落在自己那张指标卡下方，与统计卡片一起构成三栏结构。新增公开方法 `pane_range()` 供测试断言"每条序列按自己的数据缩放"。取消了原先浮在图上的图例框，改为每格上方标序列名+当前值
  - **`_draw_pane_title()` 的画刷未复位 bug**：它现在跑在 `_draw_grid()` 之前（旧版图例是最后画的），色块画刷会被网格那句 `drawRect()` 继承，把整格填成实心色块。**这个只有实际渲染出来才看得见，测试全绿**——离屏跑一次 `run_gui` 截图才发现，是本项目第 N 次印证"测试通过 ≠ 功能可用"
  - **统计信息卡片由竖排改横排**，并加 `setMinimumHeight(150)`。原先竖排套在 `QScrollArea` 里：滚动区会主动让出高度，而同排的控制面板靠子控件最小高度把整行撑高，结果三通道只有两张卡可见、噪声要滚动才看得到（为论文截图时发现）。做法与实时数据表 `setMinimumHeight(170)` 同源
  - **底部一行重新分配**：`ControlPanelWidget` 拆出 `controls_group()`/`activity_group()` 两个访问器（与 `DataPanelWidget.realtime_group()/history_group()` 同一模式），活动日志移到历史记录旁边，控制面板缩成一小条。**控制类按钮保留未删**——它们是功能需求 F8（占用状态）与 F9（控制指令下发）在界面上的唯一证据，删掉会让第 2 章列了需求、第 6 章讲了实现、第 7/9 章却拿不出界面证据
  - **设备列表文字重叠 bug**：`QListWidgetItem(device_id)` 自带的文字与 `setItemWidget()` 叠加的卡片里的同一个 device_id 被画了两遍。卡片背景不透明时被盖住，2026-08-13 面板半透明化之后透了出来，属当时未发现的回归。文字必须留在 item 上（`currentTextChanged` 与测试的 `item(i).text()` 都依赖它），故改为让 delegate 用透明色绘制
  - 公开接口、信号槽、`main_window` 与 `controller` 的连线全部未变；新增回归测试 8 条
- **仪表盘分为两页（2026-09-18）**：`MainWindow` 的仪表盘列改为 `状态横幅 + QStackedWidget(两页)`——第 1 页「实时监控」是原来的样子减去历史表，第 2 页「历史记录」由历史表独占。翻页入口是 `TopBarWidget` 新增的两个页签（`page_selected` 信号）与 `Ctrl+1`/`Ctrl+2` 快捷键，两者都汇到 `MainWindow.show_page()` 一处——分开走的话快捷键会翻了页而页签仍标着旧页。
  - **动因**：历史表原先在底部行左下角，按 stretch 折算约占仪表盘 9% 的面积（竖向 3/8 × 横向 3/10 再减状态横幅），而它是一张五列表。该行 stretch 已经调过两轮（08-18、09-08），同行另外三块都要空间，加宽是零和，只能分页。**与板载 LCD 分两页是同一个动作，但代价完全不同**：LCD 那次要加命令码 0x16、改载荷约定、改固件、烧录；这次协议/固件/`api`/`service`/`gateway` 一处未动，全部发生在 View 层内部，**未新增任何 controller 信号或 api 方法**
  - **状态横幅放在两页之外**：它的职责是"1~2 秒内认出系统是正常还是报警"，随翻页消失就不成立了
  - **翻页不重新查库**（`_build_history_page()` 的 docstring 记了原因）：实时链路一直在往表里追加，而 `DataPanelWidget.prefill_history()` 是**追加**语义，翻一次查一次会把已存的行复制一份。要做主动刷新得先给 widget 加"替换式"填充，那是另一件事
  - **底部行腾出的宽度按原比例分掉**，没有重新调参：活动日志 2/10 → 2/7、问答 3/10 → 3/7，顺序不变只是都变大了
  - `theme.py` 新增 `QPushButton#pageTab` 一组规则：无填充无边框，选中态用强调色下划线 + 亮色文字标记——只靠颜色区分在投影仪上容易看不出来
  - **已离屏实跑验证**（不只是断言）：真实 `build_simulator_runtime()` + 40 轮数据后翻页截图，第 2 页历史表实测 **1316×791 px、120 行五列**，第 1 页历史表不可见，翻回第 1 页后各分组恢复，状态横幅两页均可见，`Ctrl+1`/`Ctrl+2` 就位
  - **历史区改为每通道一列（2026-09-18 当日追加，用户看过第一版后提的）**：`_history_list` 一张五列表 → `_history_tables` 每通道一张三列表（接收时间/数值/状态），各自独立滚动，列标题写明通道、单位与供数设备（设备不做第四列——三列分宽度后 `sim-env-1-noise` 放进单元格只会被省略号截掉）。**刻意不按时刻并成一张表**：三通道不同时到达（一轮约 3.09 s，轮内相差几百毫秒），对齐后丢一帧就会把第 N 轮的温度与第 N+1 轮的湿度排进同一行——每个数都真、所属时刻却错，而界面上看不出来，与 09-09「跨时间问题」同类。显示上限同时由"三通道共用 500 条"改为**每列各 500 条**。未登记的通道会在首次上报时**动态获得一列**，不会因为"没有它的列"被悄悄丢掉
  - **读数按通道定小数位（同日）**：`channel_display` 新增 `CHANNEL_DECIMALS`/`channel_decimals()`/`format_value()`，温度与噪声 2 位、**湿度 0 位**（AHT20 湿度 ±2 %RH，写 `56.27 %` 是虚假精度）；**未登记通道原样输出不重新格式化**——取整的依据是知道传感器精度，对没听说过的通道不成立，把 `7` 写成 `7.00` 是反方向的虚假精度。实时表与历史表共用同一个格式化函数，同一读数在同一窗口里不会有两种写法。**取整只发生在显示这一步**，存储、问答引用、上云用的都仍是原始浮点。**两端已统一（同日稍晚）**：`ChannelFormat.DEFAULT_DECIMALS` 由 1 改为 2，APK 已重打；PC 指标卡也由写死的 `.1f` 改为共用 `format_value`，于是指标卡、实时表、历史表、手机卡片、手机历史页五处同一口径。**代价是大号数字多一位、9.9→10.0 这类进位的横向跳动更频繁**，取的是「一个读数只有一种写法」。验包方式见下一条
  - **APK 重打与验包（2026-09-18）**：`app-debug.apk` **6,677,662 字节，与上一版一模一样大**——这不是没打成功，`%.1f`→`%.2f` 是同长度的一字之差。**常规验包手段在这里全部失效**：类名照旧都在（`ChannelFormat` 本来就在包里），而格式串是运行时用 `"%.${decimals}f"` 拼的，dex 里根本搜不到 `%.2f` 这个字面量。改用对照实验：记下 `classes3.dex` 的 CRC（`f529b364`）→ 把常量改回 1 重打（CRC 变为 `47d8a32e`，字节数不变）→ 改回 2 重打（CRC 回到 `f529b364`）。**这才证明了那个常量确实进了包**，而不只是证明「构建没报错」
  - 新增回归测试 32 项（`test_top_bar.py` 5、`test_main_window.py` 8、`test_data_panel.py` 11、`test_channel_display.py` 5、`test_metric_card.py` 2、Android `ChannelFormatTest` +1），改了 7 条既有断言（4 条引用 `_history_list` 这一私有结构，`test_run_gui.py` 温度 `25.5`→`25.50`，`test_metric_card.py` `26.4`→`26.40`，Android 温度 `25.5`→`25.53`）——`DataPanelWidget` 早在 08-13 就把"两个 group 要能各放各处"钉成了 `test_realtime_and_history_groups_are_independently_placeable`
- **测试状态**：`tests/ui/` **17 个文件 181 个用例**（2026-09-09 实测；下列为 08 月那轮改造的记录：`test_top_bar.py`/`test_metric_card.py`/`test_status_banner.py`/`test_device_list_item.py`/`test_channel_display.py`/`test_background_widget.py` 均为新增；`test_data_panel.py`/`test_statistics_panel.py`/`test_device_panel.py` 因表格/卡片改造调整了对应用例；其余既有文件全部不变通过）+ `tests/scripts/test_run_gui.py` 8 个用例 + `tests/scripts/test_virtual_stm32.py` 10 个用例，全部通过

### Verification Tooling（scripts/，硬件在环验证工具）

- **已实现文件**：`scripts/virtual_stm32.py`
- **核心功能**：`build_frame()`——按当前 `protocol` 格式（`DATA_REPORT_CODE=0x01`，JSON payload）编码一帧；`run()`——复用 `device/sensors/` 的三个传感器模拟器生成贴近真实的数值，通过**真实** `SerialChannel` 周期性发送。设计上刻意把 `DATA_REPORT_CODE` 硬编码为字面量而非从 `application.manager` import——因为该脚本扮演的是"设备侧"，真实 STM32 固件也只能在 C 里写死这个值，两边只通过协议规范对齐、不共享代码
- **用途**：配合一对虚拟串口（如 Windows 下的 com0com）与 `scripts/run_gui.py --mode hardware` 配对，可以在**完全没有真实 MCU** 的情况下，用真实字节流（而不是内存 mock）走通整条 Hardware 模式接收链路——参见 `docs/05_Test/Virtual_STM32_Test.md`
- **测试状态**：`tests/scripts/test_virtual_stm32.py` 10 个用例，验证生成的帧能被真实 `protocol.decoder.decode()`、真实 `HardwareDeviceReceiver`、真实 `HardwareRuntimeRunner` 正确解析，全部通过

### Sensor Simulation Layer

- **已实现文件**：`src/device/sensors/{__init__,channels,generators,humidity,noise,temperature}.py`（Device 侧）+ `src/service/sensor_data_processor.py`（Service 侧）
- **核心功能**：
  - `TemperatureSensorSimulator`（20~40℃，平滑随机游走）/ `HumiditySensorSimulator`（40~80%，变化更缓慢）/ `NoiseSensorSimulator`（40~60dB 基线 + 短时峰值）—— 均为 `SimulatorDevice` 子类，未修改 `SimulatorDevice` 本身
  - `SensorDataProcessor`：订阅 `DataService`，维护每 (device_id, channel) 的当前值/最大值/最小值/平均值；阈值报警规则（**2026-09-08 起为区间制 `AlarmBand`**：湿度 30~75 %RH 双向，温度 >35 ℃、噪声 >80 dB 单边上限）。三套回调并存：`on_alarm()`（仅超限时触发）、`on_status()`（2026-08-12 新增，每次评估都触发，携带 `triggered: bool`，用于 UI 判断"何时恢复正常"，只对有阈值规则的三个 channel 有效）、`on_statistics()`（2026-08-12 新增，对**任意**数值 channel 触发，携带 `ChannelStatistics` 快照）
- **测试状态**：`tests/device/sensors/` 4 个文件 32 用例 + `tests/service/test_sensor_data_processor.py` **40 用例**（2026-09-09 增补回差与确认周期）+ `tests/integration/test_sensor_pipeline.py` 4 用例，共 **76 个用例**，全部通过
- **已完全接入**（报警 2026-08-12 上半场，统计 2026-08-12 下半场）：`SensorDataProcessor` 已通过 `ApplicationRuntime.watch_alarms_for()`/`subscribe_alarm_status`/`subscribe_statistics` + `ui/controller.py`/`main_window.py` 接入界面，报警（活动日志红字+数据行标红）与统计（独立的 `StatisticsPanelWidget`）现在都能在界面上看到，`get_statistics()` 的能力也已完全暴露。详见 `docs/05_Test/Hardware_Simulation_Mode.md`"阈值报警"一节

### STM32 Firmware（`firmware/stm32f407/`，硬件侧，独立于 `src/` 的 Python 工具链）

- **定位**：STM32F407ZGT6（正点原子探索者V3）第一版正式固件，与 `src/` 完全独立的 Keil MDK + STM32 HAL + ARM Compiler 5.06 工程，`scripts/virtual_stm32.py` 扮演的"虚拟设备"角色的真实硬件实现；不属于本文档第 2 节其余小节所描述的 Python 分层架构（`core`/`device`/.../`ui`），但通信协议（帧格式、CRC-32）与 PC 端 `src/protocol/` 严格一致，是同一套契约的两端实现
- **已实现文件**（`Drivers/BSP/` 下按职责分为 10 个模块）：`PROTOCOL/`（CRC-32 + PC↔STM32 帧编解码）、`PC_LINK/`（USART1 驱动 + 拼帧状态机）、`BOARD/`（`HAL_UART_MspInit` 集中管理 USART1/2/3 引脚）、`MODBUS/`（Modbus RTU CRC16）、`NOISE_USART/`（USART3 驱动，RXNE+IDLE 中断）、`NOISE_SENSOR/`（Modbus 请求/响应/超时/dB换算）、`SOFT_I2C/`（软件 I2C，SDA=PE0/SCL=PE1）、`AHT20/`（温湿度驱动，含 CRC8）、`DEBUG_LOG/`（USART2 独立调试口）、`SENSOR_DATA/`（统一读数结构体）；`User/main.c` 为 3 秒一轮的采集周期状态机，三通道（`temperature`/`humidity`/`noise`，与 `src/device/sensors/channels.py` 的 channel 字符串一致）分别上报
- **验证状态（2026-08-19 完成三通道全部验证；2026-09-07 更正本条）**：AHT20 温湿度链路与噪声传感器链路**均已实机验证通过**——软件 I2C 时序、AHT20 驱动与 CRC8、USART1 协议帧上报于 2026-08-16 在真板子上跑通；`noise_usart.c` 的寄存器级 IDLE 中断与 Modbus 请求/响应于 2026-08-18 传感器到货后跑通，1 小时连续运行应答成功率 100%（1163/1163）。`board_uart_msp.c` 中"PB10/PB11 能否作原始 TTL"这一全项目置信度最低的推断项亦已实测闭环。**本条上一版（2026-08-16）写的是"噪声传感器链路仍未实机验证，等传感器到货"，与本文件 5.5 节自相矛盾，已更正。** 历史记录：2026-08-14 已在 Keil 实际编译通过（`0 Error(s), 0 Warning(s)`，`Code=17832 RO-data=1092 RW-data=60 ZI-data=2412`，HEX 正常生成）。CRC-32/协议帧编码/Modbus CRC16/Modbus 请求响应解析/AHT20 数据换算+CRC8 五处纯逻辑已用 Python 等价实现或厂商手册/官方驱动给出的真实数据交叉核对；`noise_usart.c`（寄存器级 IDLE 中断）、`soft_i2c.c`（GPIO 位翻转时序）、`board_uart_msp.c`（三路 UART 引脚复用，含 PB10/PB11 是否可作原始 TTL 的推断）当时**尚未实机验证**——硬件尚未到货，如实标注为"软件逻辑已完成，实机验证待硬件到货"，不声称已完成硬件功能验证。**（以上"尚未实机验证"是 2026-08-14 当时的判断，三处均已于 08-16／08-18 实测闭环，见本条开头。）**
- **详细方案与进度**：`docs/09_STM32Hardware/STM32F407_硬件落地方案.md`（架构/引脚分配/协议细节/待确认事项清单）
- **实机上板指南**：`docs/09_STM32Hardware/STM32F407_上板联调与测试手册.md`（硬件到货后从"不开电"状态开始的十阶段联调手册，含硬件清单、上电前检查、分模块测试、PC端验证、故障排查表）

### Gateway Layer（`src/gateway/`，PC 内置网关，供 Android 调用）

- **已实现文件**：`server.py`（FastAPI 应用：**9 个 REST 端点** + `/ws`；2026-09-18 核对实测，此前文档记的 7 停在 2026-08-15，其后 09-08 加了 `/assistant/ask`、09-17 加了历史查询）、`event_hub.py`（同步回调→asyncio 的线程安全桥接，每订阅者有界队列、满时只丢自己最旧的消息）、`events.py`（三种 WebSocket 消息序列化）、`channel_units.py`（channel→单位映射，**2026-09-18 起转读 `core/channel_display.py`，不再是副本**）
- **2026-09-23 扩展**：新增 `GET /ventilation`、`PUT /ventilation/thresholds`、`PUT /ventilation/mode`、`GET /link/statistics` 四个 REST 端点（共 13 个）与 `fan_decision`/`assistant_detail`/`link_event` 三种 WebSocket 消息；`/assistant/ask` 的响应附带问答追溯。原有字段不变，Android 无需改动。`tests/gateway/` 现为 **39 个用例**（`test_server.py` 33 + `test_events.py` 6）
- **架构定位**：与 `ui/` **平级**，同为 `api.ApiInterface` 的消费方（`ui/` 转成 Qt 信号，`gateway/` 转成 HTTP/WebSocket）；不是新架构层，未改动 `api`/`service`/`application` 任何一行
- **测试状态**：`tests/gateway/` 2 个文件 **25 个用例**（`test_server.py` 19 + `test_events.py` 6，含用 `TestClient` 跑真实 ASGI 请求与 WebSocket 往返；09-08 新增手机端问答端点用例），全部通过
- **文档状态（2026-09-07 补齐）**：此前 `src/gateway/` 是 `src/` 下**唯一没有 `README.md`** 的包，且 `docs/02_Architecture/` 下四份架构文档**全部不提它**——按 `CLAUDE.md`"没有文档说明的功能不视为开发完成"，这是一笔明确的工程债。本次已补齐：新建 `src/gateway/README.md`（职责、7 REST + 1 WS 端点表、设计约束、依赖关系、单位映射重复的遗留说明、测试情况）；`Software_Structure.md` 新增"实际落地结构（编码阶段实况）"一节记录当时的 9 个包与依赖方向（2026-09-08 随 `src/llm/` 加入更新为 10 个）；`Multi_Client_System_Architecture.md` 新增 2.3.1 节记录本包是第 2.3 节那个"PC 本地网络接口层"的实现落点；`System_Architecture.md` 的 UI Layer 一节补记 Presentation Layer 的多端展开

### 七个一键启动器（2026-08-15 新增三个，08-16 增 `run_all_界面加网关.bat`，08-17 增 `collect_data_实验数据采集.bat`，09-10 增 `start_llm_启动本地模型.bat`/`stop_llm_停止本地模型.bat`）

| 双击 | 用途 | 背后脚本 |
| --- | --- | --- |
| `run_gui_模拟数据界面.bat` | PC 界面·模拟模式 | `scripts/run_gui.py` |
| `run_gui_hardware_真实硬件界面.bat` | PC 界面·硬件模式（交互选串口） | `scripts/run_gui_hardware.py` |
| `run_api_server_手机网关.bat` | Android 网关（交互选模式/串口，并打印手机要填的 IP） | `scripts/run_api_server_launcher.py` |
| `run_all_界面加网关.bat`（2026-08-16 新增） | **PC 界面 + Android 网关同时跑**，共用一条串口 | `scripts/run_all_launcher.py` → `scripts/run_all.py` |
| `collect_data_实验数据采集.bat`（2026-08-17 新增，08-18 扩为 7 种预设） | 论文实验数据采集，预设「试运行 / 温湿度阶跃 / 长时间稳定性 / **噪声试运行** / **噪声阶跃响应** / **环境本底噪声** / 自定义」 | `scripts/collect_data_launcher.py` → `scripts/collect_thesis_data.py` |
| `start_llm_启动本地模型.bat`（2026-09-10 移到根目录） | 本地语言模型：探测服务、按需拉起、确认已下载、发真实请求预热 | `scripts/start_llm.py` |
| `stop_llm_停止本地模型.bat`（2026-09-10 新增） | 本地语言模型：卸载模型（默认）/ 连服务与托盘程序一起停（`--server`） | `scripts/stop_llm.py` |

> **硬件模式下要两端同时看数据，必须用 `run_all_界面加网关.bat`**，不能同时双击 `run_gui_hardware_真实硬件界面.bat` 和 `run_api_server_手机网关.bat`——原因见下方"单串口双消费方"。

两个交互式启动器解决的都是"每次都要手动查、且很容易查错"的问题，且都做了**主动排除错误项**的识别，而不是简单取第一个：

- **串口选择**（`run_gui_hardware.py`）：本机在**没插板子时**就已有 COM3/COM4 两个蓝牙虚拟串口（`BTHENUM` hwid）。启动器按 hwid 识别 CH340/CP210/FTDI 等 USB 转串口特征并排除蓝牙口，标注出"可能是开发板"的那个。
- **编码 bug 修复（2026-08-16）**：`run_api_server_手机网关.bat` 选模式 1 后崩溃，`UnicodeDecodeError: 'gbk' codec can't decode byte 0x91`。根因是 `lan_address.py` 调 PowerShell 时用了 `text=True`——它按**系统区域编码**（中文 Windows 上是 GBK）解码，而网卡描述是厂商字符串，含非 GBK 字节。失败方式很隐蔽：解码错误发生在 `subprocess` 的**读取线程**里，`subprocess.run()` 仍正常返回，只是 `stdout` 变成 `None`，于是在几行之后以 `AttributeError: 'NoneType' object has no attribute 'strip'` 爆出来，现场与根因完全对不上。修复三处：让 PowerShell 输出 UTF-8（脚本前置 `[Console]::OutputEncoding`）、Python 侧显式 `encoding="utf-8", errors="replace"`（网卡名乱一个字符只是观感问题，IP 本身是 ASCII 不受影响）、`stdout` 兜底判空。已实测：`find_candidates()` 仍正确 9 选 1 得到 `192.168.2.153`，`--mode simulator` 端到端起服务后 `/health`、`/devices` 均正常、`published_count` 持续增长
- **局域网 IP 识别**（`scripts/lan_address.py`）：本机有 **9 个 IPv4 地址**（Mihomo 代理隧道、WSL、VirtualBox、蓝牙、TAP、两个 Hyper-V、两个 APIPA、真实 WLAN）。**最流行的探测写法（`socket.connect('8.8.8.8')` 再读 `getsockname`）在本机返回 `198.18.0.1`，即 Mihomo 隧道地址，填到手机上永远连不上**。该模块改为枚举全部网卡并按"虚拟网卡关键词 + 地址段"打分排序，实测 9 选 1 正确挑出 `192.168.2.153`（WLAN / Intel Wi-Fi 6E）。

---


## 3. 当前测试状态

| 项目 | 结果 |
| --- | --- |
| `pytest` | **1266 passed**（2026-09-18 实测：仪表盘分两页 13 项——`test_top_bar.py` 5、`test_main_window.py` 8；历史区分三列与小数位 18 项——`test_data_panel.py` 11、`test_channel_display.py` 5、`test_metric_card.py` 2；删除的拒绝 10 项与上传的按钮 15 项——`test_intent.py`、`test_phrasing.py`、`test_assistant.py`、`test_assistant_panel.py` 5、`test_controller.py` 3）；此前 **1210 passed**（2026-09-17 第九次复测，启动器真启动守卫 18 项：带 argparse 的验 `--help`、纯交互的验无 import 错误、另一档 `-P` 验不依赖项目根）；同日 **1192 passed**（第八次复测，`.bat` 启动器格式守卫 28 项：九个文件各验 CRLF、UTF-8、含中文须有 chcp）；同日 **1164 passed**（第七次复测，新增只读查看脚本 `cloud_view` 11 项）；同日 **1153 passed**（第六次复测，endpoint 填法容错 6 项：控制台的"外网访问域名"带桶名前缀，`oss2` 会再拼一次，实测连踩两次后由 `normalise_endpoint()` 剥掉）；同日 **1147 passed**（第五次复测，P3 上传器与接线：上传器 20、接线 6；**真实上传尚未验证**）；同日 **1121 passed**（第四次复测，P2 归档导出落地：`cloud_sync` 19、导出台账 14、`query_range` 8）；同日 **1080 passed**（第三次复测，P1 网关端点与界面取数落地：网关 +5（含替换掉的 404 断言）、`ui/controller` +3、`data_panel` +5）；同日 **1068 passed**（2026-09-17 第二次复测，P0 历史记录落地：存储 16、记录器 15、端口 10、`LocalApi` 6、启动器守卫 3，另有 `tests/api/test_interface.py` 的契约守卫登记了 `query_history`）；此前 **1019 passed**（0 failed，0 skipped）—— 2026-09-17 实测（09-15 为 1009，+10 是问答日志：`tests/scripts/test_question_log.py`，其中一条专测跨零点归档；09-14 为 997，+12 是 09-15 的复合句拆句：`test_intent.py` 4 项、`assistant/test_assistant.py` 8 项；09-09 为 967；+16 是 09-10 的 `test_stop_llm.py` 与 `test_start_llm.py` 增补，+4 是 09-14 的问答回归测试：风扇"交回自动"2 项、"今天"不标过去时段 1 项、能力问法 1 项；+3 是同日的征询语气守卫，+7 是同日的指令模型复核） |
| `ruff check src tests scripts` | **All checks passed!** |
| `mypy src` | **Success: no issues found in 96 source files**（2026-09-18 再加 `service/assistant/export_status_port.py` 与 `application/export_status.py`）。此前：**94 source files**（P3 再加 `src/storage/oss_uploader.py`；`oss2` 无类型存根，已在 `pyproject.toml` 加 mypy override）。此前：**93 source files**（2026-09-17：P0 新增 `src/storage/sqlite_history.py`、`service/history.py`、`application/history_recorder.py`，P2 再加 `src/storage/export_ledger.py`；此前 88） |
| Android `gradle assembleDebug` | **BUILD SUCCESSFUL**，产出 `app-debug.apk`（6,677,662 字节，**2026-09-17 21:36 历史页落地后重建**）。已验包内实际含 `HistoryActivity`（classes5.dex）、`HistoryParser`（classes4.dex）与四个新资源，且二进制 Manifest 里四个 Activity 全部注册——构建成功不等于功能进包，这两项单独验过。此前：6.19MB，2026-08-16 第二阶段 UI 后重建 |
| Android `gradle lintDebug` | **BUILD SUCCESSFUL**，**0 error / 18 warning**（2026-09-17 历史页落地后复跑；此前 2026-08-16 新增该检查项时同为 0 error） |
| Android `gradle testDebugUnitTest` | **41 passed**（2026-09-18 实测：`MessageParserTest` 13、`StallDetectorTest` 9、`HistoryParserTest` 11、`ChannelFormatTest` 8——小数位由 1 位改 2 位并补了噪声一项；09-17 为 40 项、`ChannelFormatTest` 7；此前记的 10 是第一阶段的旧数）。**须在纯英文路径下运行**——中文路径下四个测试类全部 `ClassNotFoundException`，`--rerun-tasks` 无效，见 `android/gradle.properties` 与 5.2 节 |
| Android 真机端到端联调 | **第一阶段已通过**（2026-08-15，真机 + simulator 模式）；**第二阶段 UI 已通过**（2026-08-16，含断线自动重连）；**真实硬件模式已通过**（2026-08-16，`run_all_界面加网关.bat` 硬件模式下手机与 PC 同时显示真实 AHT20 读数）。见 5.2 / 5.4 / 5.5 节 |

按目录的用例分布（**2026-09-09 由 `pytest --collect-only -q` 实测重新统计，合计 967；2026-09-14 复测为 987，当日再增征询语气守卫 3 项与指令复核 7 项合计 997，`tests/scripts/` 与 `tests/service/` 两行变化，已就地更新；2026-09-15 复测为 1009，只有 `tests/service/` 一行变化（复合句拆句 12 项）；2026-09-17 复测为 1019，只有 `tests/scripts/` 一行变化（问答日志 10 项）；**同日历史记录与上云四期落地后复测为 1121**，`service`/`application`/`api`/`ui`/`gateway`/`storage`/`scripts` 七行变化，已按 `pytest --collect-only` 实测逐行订正——其中 `application`、`api` 两行此前在 P0 时漏更，一并补上**）：

| 目录 | 用例数 | 较 09-08 变化 | 变化来源 |
| --- | --- | --- | --- |
| `tests/core/` | 13 | — | |
| `tests/device/`（含 `sensors/` 32） | 76 | — | |
| `tests/protocol/` | 28 | — | |
| `tests/communication/` | 40 | — | |
| `tests/service/` | 316 | +154 | 2026-09-15：复合句拆句，`test_intent.py` +4（分句、紧挨数字的空格不断句、体感不算提问、"没"字问与正反问）、`assistant/test_assistant.py` +8（问与指令并存、复核只送指令段、分歧反问保留已答部分、两问并答、体感铺垫不单答、同一问题不拆、两条指令不拆、拆句后阈值数值不丢）；2026-09-14：`test_intent.py` +7（风扇"交回自动"2、"今天"不标过去时段 1、能力问法 1、征询语气守卫 3）、`assistant/test_assistant.py` +7（指令的模型复核：一致执行、分歧反问、否认、未答作废、空回复照执行、无模型即时执行、补通道不复核）；问答四档交互性：`assistant/test_assistant.py` 64、`test_intent.py` 39、`test_phrasing.py` 31、`test_retrieval.py` 18、`test_control.py` 12；`test_sensor_data_processor.py` 40（回差与确认周期） |
| `tests/application/` | 144 | +25 | `answer_dispatcher` 15 等问答下发链路；2026-09-17 P0 增 14（`test_history_recorder.py`：回调里不落盘、攒批与超时、坏值计数不连累同批） |
| `tests/api/` | 36 | — | 2026-09-17 P0 增 6（`LocalApi.query_history`：未挂存储返回空、未知设备不报错、limit 与时间范围转调不走样） |
| `tests/ui/` | 189 | +3 | 问答面板与通风卡片的增补 |
| `tests/gateway/` | 29 | +8 | 手机端问答端点 |
| `tests/integration/` | 32 | +2 | |
| `tests/llm/` | 19 | +2 | |
| `tests/storage/` | 59 | +33 | 2026-09-17 新增：`SqliteHistoryStore` 16（写入可查、重开仍在、混精度时间戳排序、无效读数照存、坏库不抛）+ `query_range` 3 + P2 的 `SqliteExportLedger` 14（幂等靠 UNIQUE、待发队列由早到晚、上传后仍留作幂等依据、台账坏掉不抛） |
| `tests/scripts/` | 229 | +64 | 2026-09-17：`test_question_log.py` +10（配对落盘、新问题冲走旧的、手机端标记、误执行留痕、按天分文件、**按提问时刻归档**、日志坏掉不抛异常、无主的迟到答案、缺字段仍可记）； `test_collect_thesis_data.py` 25、`test_start_llm.py` 16（启动脚本判定逻辑，09-09 时 9 项）、`test_stop_llm.py` 10（2026-09-10 新增） |
| **合计** | **1019** | **+258** | |

> 复现该表：`QT_QPA_PLATFORM=offscreen pytest --collect-only -q`（按目录汇总各文件计数）。
>
> **历史快照**：462 / 471 / 474 → 513（2026-08-18~19 的 UI 重构与 bug 修复新增 39 个：
> `test_frame_stream.py` 7、`test_collect_data_launcher.py` 5、采集脚本 11、UI 10、其余 6）
> → 627（2026-09-07 通风 + 语音告警新增 114 个）
> → 650（同日 LCD 新增 23 个：`alarm_state_dispatcher` 11、`hz_font_to_c` 12）
> → **761**（2026-09-08 环境问答新增 88 个、启动器接线回归 10 个、试用中发现的两个 bug 的回归 16 个）。

> 复现命令（PyQt6 测试在无显示环境下需要 `QT_QPA_PLATFORM=offscreen`）：
> ```bash
> QT_QPA_PLATFORM=offscreen pytest
> ruff check src tests scripts
> mypy src
> ```

---


## 4. 当前架构数据流

### Simulator 模式（已完整验证，可运行 `run_gui_模拟数据界面.bat` 直接体验）

```
SimulatorDevice（含 sensors/ 预设）
        │  .generate(channel) -> DataPoint
        ▼
Protocol（encode/decode，经 LoopbackChannel 收发一圈，验证编解码正确性）
        ▼
DataService（InMemoryDataService.publish）
        │
        ├──> SensorDataProcessor（统计 + 报警评估，均已接入 UI）
        │       ├──> api.subscribe_alarm_status -> MainController.alarm_status_changed
        │       │     -> 活动日志红字 / 数据表格行标红（自动恢复）
        │       └──> api.subscribe_statistics -> MainController.statistics_changed
        │             -> StatisticsPanelWidget（独立表格，任意数值 channel 都显示）
        │
        └──> API（LocalApi.subscribe_data 的回调）
                 ▼
              UI（MainController -> MainWindow 各 widget 实时展示）
```

### Hardware 模式（软件链路已完整打通，`--mode hardware` 可直接启动；**已在真实 STM32F407 上验证通过**）

> 本小节标题原为"固件已就绪但硬件未到货，尚未连过真实 MCU"，写于硬件到货前，
> 2026-09-07 更正：开发板 2026-08-16 到货、噪声传感器 2026-08-18 到货，三通道均已实机跑通。

```
真实 MCU（固件见 firmware/stm32f407/，已实机验证通过）
／scripts/virtual_stm32.py（已实现，扮演虚拟 MCU，无硬件时使用）
        │  UART 发送符合 Protocol 帧格式的字节流
        ▼
SerialChannel.receive()
        ▲
        │  QTimer.timeout.connect(runner.run_once)  ← scripts/run_gui.py 里装配
        │
HardwareRuntimeRunner.run_once()
        ▼
HardwareDeviceReceiver._process_frame()
        │  protocol.decode() -> 过滤 DATA_REPORT 帧、校验 wire_id、解析 JSON payload
        ▼
DataPoint（关联到某个 RemoteDevice 的 device_id）
        ▼
DataService.publish()
        │
        ├──> SensorDataProcessor（同 Simulator 模式，代码完全复用，报警+统计均已接入 UI；
        │     Hardware 模式需要 build_hardware_runtime() 显式调用
        │     runtime.watch_alarms_for(device) 才能接入两者——见 Application Layer
        │     一节 2026-08-12 记录的 bug，统计信息复用了同一处修复，未再踩坑）
        │
        └──> API/UI（同 Simulator 模式，代码完全复用）
```

**两条链路从 `DataService.publish()` 往下完全一致**——这是本次一系列任务反复验证并强调的架构不变量：`SensorDataProcessor`/`api`/`ui` 不知道、也不需要知道数据来自模拟器还是真实串口。启动方式：`python scripts/run_gui.py --mode hardware --port COM3`（详见 `docs/05_Test/Runtime_Mode.md`）。已在 2026-08-12 通过 WSL + socat 虚拟串口环境完整验证过数据/命令/报警三条链路，见第 10 节归档。

### 完整三端数据流（2026-08-15 起）

`ApiInterface` 之上现在有**两个平级消费方**，两条支路互不影响、可同时运行（各自独立进程、各自持有一个 ApplicationRuntime）：

```
        （Simulator 模拟器  或  Hardware 真实 STM32）
                        │
                        ▼
              DataService.publish()
                        │
                        ▼
                api.ApiInterface
                        │
        ┌───────────────┴───────────────┐
        ▼                               ▼
  ui/（PyQt6）                     gateway/（FastAPI）
  MainController→Qt信号            REST + WebSocket
        │                               │
        ▼                               ▼
   PC 桌面界面                  局域网 ──> Android 客户端
```

**关键不变量**：`gateway/` 与 `ui/` 谁都不知道对方存在，也都不知道数据来自模拟器还是真实串口——所以硬件到货后，PC 界面与 Android 端预期都**零改动**，只需换启动参数。

### 单串口双消费方（2026-08-16 硬件到货后暴露并解决）

上图"两个平级消费方"在 **Simulator 模式**下可以是两个独立进程（各生成各的模拟数据）。**Hardware 模式下不行**：物理串口是独占资源，第二个进程调用 `SerialChannel.connect()` 会直接失败——

```
SerialConnectionError: failed to open serial port 'COM10':
PermissionError(13, '拒绝访问。')
```

这不是 bug，是"一块板子、一根线、只能有一个读取者"的物理事实。此前没暴露，是因为一直没有真板子；本文档旧版"两条支路各自独立进程、可同时运行"的说法**只对 Simulator 模式成立**，已在此更正。

**解决方式**：新增 `scripts/run_all.py`（+ `run_all_launcher.py` + `run_all_界面加网关.bat`）——**一个进程、一个 `ApplicationRuntime`、一条 `SerialChannel`，同时挂两个消费方**。这正是架构本来的设计意图（`ui/` 与 `gateway/` 是 `ApiInterface` 的平级消费方），不是绕过架构的权宜之计：

- **Qt 主线程**：`QTimer` 驱动 `runner.run_once()`，所以每次 `DataService.publish()` 与随之而来的界面刷新都发生在 Qt 线程上，符合 PyQt6 要求
- **后台线程**：uvicorn 及其 asyncio 事件循环。`EventHub.publish()` 的 docstring 早就写明"可从任何线程安全调用"（内部走 `loop.call_soon_threadsafe`），这里正是它设计时针对的场景
- **延迟**：串口字节只解码一次、只发布一次，向两个消费方扇出，手机侧仅多一次 `call_soon_threadsafe`。没有轮询、没有中转、没有二次解析

**已实测**：
- 模拟模式（2026-08-16，离屏真实进程）：`/health` 显示 `published_count` 4 秒内从 45 增至 81（3 通道 × 3Hz），`/devices`、`/devices/{id}/status` 均正常，Qt 事件循环与 uvicorn 并存无冲突
- **硬件模式（2026-08-16，用户在真板子上验证）：`run_all_界面加网关.bat` 下 PC 界面与 Android 手机同时显示真实 AHT20 读数与曲线**，证实"一条串口、一次解码、扇出两个消费方"在真实硬件下成立，两端都没有出现丢数、错位或延迟异常

`tests/scripts/test_run_all.py`（4 用例）把"UI 与网关共用同一个 runtime/DataService"这条不变量钉死——一旦将来有人改回建两个 runtime，测试会立刻失败，而不是等到插上真板子才发现。

---


## 5. 当前未完成任务

| 任务 | 状态 |
| --- | --- |
| ~~Hardware Runtime 持续驱动机制~~ | **已完成**：`HardwareRuntimeRunner` + `scripts/run_gui.py` 里的 `QTimer` 驱动 |
| ~~GUI 侧硬件模式启动入口~~ | **已完成**：`scripts/run_gui.py --mode hardware --port COM3` |
| ~~无硬件字节流级验证工具~~ | **已完成**：`scripts/virtual_stm32.py`（真实串口发送，非内存 mock） |
| ~~真实 UART 接入~~ | **已完成（2026-08-12）**：WSL + socat 虚拟串口对 + `virtual_stm32.py` + `run_gui.py --mode hardware`（GUI 经 WSLg 显示）已验证通过，实时看到真实字节流收发的 temperature/humidity/noise 数据；过程中发现并修复了 `HardwareDeviceReceiver` 的字节流拼帧 bug（见第 2 节 Application Layer）。原生 Windows 下真实串口（`SerialChannel` 直接用 COM 口）不受 WSL 限制，见第 10 节 |
| ~~**STM32 实机验证**~~ | **已完成（2026-08-19；本行于 2026-09-07 更正）**：开发板与 AHT20 于 08-16 到货跑通温湿度两通道；HH_07.06 噪声传感器于 08-18 到货，USART3/Modbus 链路（含 PB10/PB11 能否作原始 TTL 这一全项目置信度最低的推断项）实机验证通过；08-19 完成三通道 1 小时稳定性、阶跃响应、越限报警、环境本底四项实验，Modbus 应答成功率 100%（1163/1163）。**本行上一版写的是"噪声传感器尚未到货、仍未实机验证"，已过期。** 详见 5.5 节 |
| ~~Hardware 模式命令下发会崩溃~~ | **已修复（2026-08-12）**：`DeviceManager.deliver()` 现在对 `RemoteDevice` 真正等待设备侧应答（带超时、优雅失败），`virtual_stm32.py` 也已实现命令监听/应答逻辑，硬件在环演示中验证"发送命令"能收到真实回复且不影响后续数据流。详见第 2 节 Application Layer 与第 10 节 |
| **二进制 payload 设计（未来）** | 当前 Simulator/Hardware 两模式共用的 payload 是 JSON 文本（`{"channel":...,"value":...}`），仅为 phase-1 内部约定；真实 STM32 上 JSON 解析开销大，预计后续需要重新设计紧凑二进制格式（届时只影响 `application/manager.py`+`application/hardware_runtime.py`+`scripts/virtual_stm32.py` 里的编解码约定，`protocol`/`communication` 不受影响） |
| **历史数据导出** | 完全未实现（如 CSV 导出），是"传感器验证性毕设"话题里讨论过的候选功能，尚未定案是否要做、如何做 |
| ~~阈值报警 UI 增强~~ | **已完成（2026-08-12）**：`SensorDataProcessor` 已通过 `api.subscribe_alarm_status` 接入 `ui`——活动日志红字报警 + 数据表格行标红，恢复正常后自动清除颜色；已在 WSL 硬件在环环境实测通过。详见第 2 节 Service/Application/API/UI Layer 与 `docs/05_Test/Hardware_Simulation_Mode.md`"阈值报警"一节 |
| ~~统计信息 UI 展示~~ | **已完成（2026-08-12）**：`SensorDataProcessor.get_statistics()` 已通过 `api.subscribe_statistics` + 新增独立 widget `StatisticsPanelWidget` 接入界面，当前值/最小值/最大值/平均值/样本数按 (device_id, channel) 实时展示，不限于报警三通道；复用了报警接入时修好的 `watch_alarms_for()` 机制，Hardware 模式无需额外修复；已在 WSL 硬件在环环境实测通过 |
| ~~界面整体美化 / 产品级视觉重构 / 信息层级与空间布局优化~~ | **已完成（2026-08-13，三步连续完成）**：深色工业监控主题（QSS+QPalette）→ 四层仪表盘布局重构（顶部栏/指标卡/大图/数据+统计/报警+历史+控制）→ 空间权重重新分配（"数据是主角"，实时数据表 5 列+加大字号行高、统计信息改卡片式、控制面板视觉弱化）。全程纯 UI 展示层改动，`protocol`/`communication`/`service`/`application`/`api` 与阈值/统计算法零改动；`MainController` 信号/槽接口零改动。详见第 2 节 UI Layer 三条 2026-08-13 bullet |
| ~~GUI 背景视觉层 + 面板半透明化~~ | **已完成（2026-08-13～2026-08-14）**：`BackgroundWidget` 绘制用户提供的个性化背景图 + 轻量遮罩；各面板 QSS 背景从不透明色改为按层级分档的 `rgba(...)`（一般信息面板最透明，活动日志最不透明）；`ChartWidget` 绘图区改为半透明填充。第一版全不透明面板未达预期后，据用户反馈重做为分层半透明，已获用户人工确认符合预期。纯 UI 展示层改动，`protocol`/`communication`/`service`/`application`/`api` 与 `MainController` 信号/槽接口零改动。详见第 2 节 UI Layer"GUI 背景视觉层"bullet |

---


## 5.3 待用户决策事项（汇总，新会话应先看这里）

> ⚠️ **2026-09-07 更新：本节 4 项中的第 2、3、4 项已不再是待决策项**——第 3 项（报警阈值）
> 已于 08-19 依据 GB 37488—2019 论证闭环；第 2、4 项（历史数据能力、二进制 payload）
> 已按用户指示**不再作为后续开发方向**，见 5.8 节。~~仅第 1 项（单位映射重复）仍然有效。~~
> **2026-09-18：第 1 项也已闭环**，本节四项至此全部了结。

以下几项**已被识别但有意未擅自执行**，需要用户拍板后才动。它们都不阻塞当前工作。

| # | 事项 | 现状 | 为什么没做 |
| --- | --- | --- | --- |
| 1 | ~~**单位映射重复两份**~~ **2026-09-18 已闭环** | ~~`ui/channel_display.py` 与 `gateway/channel_units.py` 各有一份~~ → 已抽进 `src/core/channel_display.py`，两处改为转读、公开名字不变 | 原因记录保留：`import ui.channel_display` 会执行 `ui/__init__.py` 从而连带 import PyQt6（实测拉进 5 个模块），无界面网关不应依赖 GUI 框架；且两者是架构平级模块。**这两条反对的都是"import ui"，而不是"共享定义"**——缺的只是一个两个平级模块都不拥有的落点。归档导出成为第三个消费方时补上了。已实测：import `gateway.channel_units` 拉进 0 个 PyQt 模块 |
| 2 | **历史数据能力缺失** | `service`/`application`/`api` 三层都没有历史数据能力，仅存在于 `ui/widgets/data_panel.py` 的 QTableWidget 内部 | 补它需要扩展受保护的 `api`/`service` 接口，需单独授权。当前已在 `tests/gateway/test_server.py` 写死一条"该端点返回 404"的测试，把"故意没做"这个决定固定下来，避免后人误以为是漏做 |
| 3 | **报警阈值需按地铁站场景重新论证** | 温度>35℃ / 湿度<30% / 噪声>80dB，是仿真阶段的占位值 | 需要真实环境数据与相关标准支撑，等硬件联调后再定 |
| 4 | **二进制 Payload** | 当前 PC↔STM32 用 JSON 文本 | 是否需要取决于实机联调中 JSON 解析开销是否真的成为瓶颈，不预先优化 |


## 6. 下一阶段开发建议

> ⚠️ **本节内容已被 5.7、5.8 两节部分取代（2026-09-07）。** 阅读顺序建议改为：
> 先看 **5.8 节（需求方向转变）**确认哪些遗留项已不再是待办，再看 **5.7 节**了解
> 08-21～08-31 的交付物与排版稿的真实进度，最后才看本节。本节下方"三句话"的第 3 句
> 与"当前唯一硬件阻塞项"一小节均写于噪声传感器到货之前，**其所述阻塞项已于
> 2026-08-18～19 全部闭环**（见 5.5 节），保留原文仅供追溯，不要再据其安排工作。

### 给新会话的三句话

1. **软件已全部完成**并在真实硬件上验证通过（三端 + 自动化测试全绿；当时 513 个，2026-09-08 扩展功能后为 761 个）。
2. **论文正文已全部写完**（10 章 + 摘要，约 4.9 万汉字，见 5.6 节与 `docs/07_Thesis/`）。
   全部待办已汇总在 `docs/07_Thesis/论文待办总清单.md`，按"要做什么事"分六类。
3. **真正被硬件卡住的只有三件**：噪声通道实测与五处回填、三张需三通道齐全的截图（图 7-2/8-2/9-3）、
   固件第三路串口 PB10/PB11 的 TTL 可用性验证。**其余全部可以现在做**，见下方"等硬件期间可做的事"。

### ~~当前唯一硬件阻塞项：噪声传感器 HH_07.06 尚未到货~~（**已于 2026-08-18 到货并闭环，本小节全部内容作废，仅供追溯**）

开发板与 AHT20 已到货并跑通（见 5.5 节），温湿度两通道真实读数已在 PC 端显示。**剩下的工作全部卡在噪声传感器这一个件上。** 它到货后按优先级：

1. **噪声传感器实机联调（最高优先级）**——按 `docs/09_STM32Hardware/STM32F407_上板联调与测试手册.md` 第五阶段执行（先用 USB 转 TTL 单独确认模块出厂协议模式，再接 STM32）。风险最高的一条是 **PB10/PB11 在不装 P2 跳线时能否作原始 TTL**，属文档类比推断；若不可用，改用 UART4/UART5/USART6 任一空闲串口，只需改 `board_uart_msp.c` 与 `noise_usart.c` 的引脚配置。实测结论回填 `STM32F407_硬件落地方案.md` 的"待确认事项清单"形成闭环
2. **换成真实数据后回归三端**——单看一端用 `run_gui_hardware_真实硬件界面.bat` / `run_api_server_手机网关.bat`，两端同时看用 `run_all_界面加网关.bat`（硬件模式下串口独占，见第 4 节"单串口双消费方"），预期 PC/Android 侧零改动（见下一小节）
3. 报警阈值按地铁站场景重新论证（见 5.3 节第 3 项）
4. ~~Android 断线重连实测~~ **已完成（2026-08-17）**，见 5.2 节末与第 9 章 9.6
5. ~~论文实验数据采集与第 7 章补全~~ **已完成**，见 5.6 节

### 等硬件期间可做的事（2026-08-17 重新梳理，按性价比排序）

前四项直接决定论文能否定稿与答辩表现，建议优先；后三项属加分项。

| # | 事项 | 谁做 | 说明 |
| --- | --- | --- | --- |
| 1 | ~~补中文参考文献~~ **已完成 2026-08-19**：4 条 → 11 条（F/G/H/I/J/K 六组），已插入第 1、2、7、8 章正文 | — | 检索指令模板见 `中文文献检索清单.md` 附录 A，可复用 |
| 2 | **6 条文献的缺失题录** | 用户 | [F4] 页码 / [G2] 培养单位年份 / [H2] 卷号页码 / [I3] 页码 / [J1] 页码 / [K2] 卷号页码。**需 CNKI 或维普**，Claude 够不到 |
| 3 | **新增 16 条外文文献逐条 DOI 核对** | 用户 | 定稿前必做，已发现 1 例年份/卷期不符 |
| 4 | ~~论证报警阈值与量程依据~~ **已完成 2026-08-19**：依据 GB 37488—2019（明确含「轨道交通站台」），噪声阈值论证闭环；温湿度如实标注为工程取值 | — | 见第 7 章 7.5.1、第 10 章 10.3 |
| 5 | ~~拍接线实物照片~~ **图 4-4 已完成**（图 4-5 用户决定暂不补拍） | — | 已裁去手机水印，正文引用在第 4 章 4.6.3 |
| 5 | 竞品参数逐条核对厂商手册并补入参考文献 | 用户 + Claude | 待办清单第四节第 4 项，第 3 章表中未标 ★ 的参数 |
| 6 | 取学校论文模板，生成不含写作过程块的纯净正文版 | 用户取模板 / Claude 生成 | 排版是最后一步，但模板要早点要到 |
| 7 | 可选补测：移动端时延、静默失连健康检测 | 用户 | 不影响定稿，测了可补进摘要与第 9 章 |

已完成、不必再列为待办的：~~三端回归~~（2026-08-16 硬件模式实测通过，见 5.5 节）、
~~论文实验数据采集~~（2026-08-17 完成，见 5.6 节）、~~Android 断线重连实测~~（见 5.2 节末）、
~~Android 最终 UI~~（2026-08-16 真机验证，见 5.4 节）、~~固件代码体积复核~~（2026-08-17，与 `.map` 一致）。

仍待用户授权、非必需的：历史数据能力（5.3 节第 2 项）、历史数据导出 CSV。

~~数据面板"清空历史记录"~~/~~"暂停接收"~~/~~界面整体美化（QSS 主题）~~/~~产品级视觉重构（仪表盘布局）~~/~~信息层级与空间布局优化~~/~~GUI 背景视觉层 + 面板半透明化~~/~~Simulator 模式无数据驱动的缺陷~~/~~Android 客户端第一阶段~~ 均已完成（见第 2、5.2 节）。

~~数据面板"清空历史记录"~~/~~"暂停接收"~~/~~界面整体美化（QSS 主题）~~/~~产品级视觉重构（仪表盘布局）~~/~~信息层级与空间布局优化~~/~~GUI 背景视觉层 + 面板半透明化~~ 均已于 2026-08-13～2026-08-14 完成（见第 2 节 UI Layer）。

### PC 侧（`protocol`/`communication`/`service`/`application`/`api`/`ui`）在 STM32 实机联调阶段预期不需要修改

这一判断已在历次任务报告中反复确认（详见 `docs/05_Test/Hardware_Simulation_Mode.md`），STM32 固件严格遵循了 `Protocol_Design.md`/`protocol/encoder.py` 定义的帧格式与 `DeviceManager` 期望的 ACK 应答约定，理论上可以直接替换 `scripts/virtual_stm32.py` 扮演的角色。若实机联调发现 PC 侧确实需要改动（如二进制 payload 设计，见第 5 节），届时按需评估，不属于当前已知的必须工作。

---


## 7. 开发约束

### 禁止修改

- `protocol` 接口（`src/protocol/frame.py`/`encoder.py`/`decoder.py`）
- `communication` 接口（`src/communication/interface.py`，以及已实现的 `serial.py`/`loopback.py` 也应避免改动其行为）
- `service` 接口（`src/service/data_service.py`/`control_service.py` 等抽象契约）
- `api` 接口（`src/api/interface.py`）
- `ui` 架构（MVC 分层：View 不直接访问 `api`，只能经 `ui/controller.py`；widgets 保持业务逻辑无关）

以上是贯穿最近多个任务反复重申、并已通过测试验证遵守的硬约束，新会话应继续遵守，除非用户明确要求变更并说明理由（对应 `CLAUDE.md` "修改规则"一节）。

### 必须保持

- **Simulator 模式必须继续可用**——任何新增改动都不能破坏 `SimulatorDevice`/`LoopbackChannel` 这条无硬件验证链路，`run_gui_模拟数据界面.bat` 应始终能正常打开界面并展示模拟数据
- **根目录的 `.bat` 启动器必须是 CRLF 换行 + UTF-8 编码**，含中文的还必须有 `chcp 65001`。已由 `tests/scripts/test_batch_launchers.py` 钉死，不必靠记性。
  - 起因（2026-09-17）：新写的 `cloud_sync_导出并上传.bat` / `cloud_view_查看云端.bat` 用裸 LF 换行，`cmd.exe` 解析批处理时**行结构整个散掉**——把注释碎片当命令执行，报出一串 `'rule' 不是内部或外部命令`、`此时不应有 else`，退出码 255。而 `scripts/cloud_sync.py` 本身完全正常，故障点只在 `.bat` 这层包装，错误信息与真正的原因毫无关联。
  - 普查后发现不是孤例：`collect_data_实验数据采集.bat` 同样裸 LF 且带中文，属同一种待爆的雷；`run_gui_模拟数据界面.bat`/`run_all_界面加网关.bat`/`run_api_server_手机网关.bat`/`run_gui_hardware_真实硬件界面.bat` 是裸 LF 但纯 ASCII，**侥幸能跑**——只要谁给它们加一行中文注释就会崩。九个文件已全部归一为 CRLF。
  - 用 `Write` 类工具生成 `.bat` 时尤其要注意：默认写出的是裸 LF。

---


## 8. Claude Code 新会话使用说明

**给新会话的 Claude Code**：读取本文件后，不需要重新分析全部历史对话即可直接继续开发。项目当前状态可信来源优先级为：本文件 > 各模块 `README.md` > `docs/02_Architecture/`/`docs/03_Communication/`/`docs/05_Test/` 下的设计文档 > 直接读取 `src/`/`tests/` 源码。若本文件与代码实际状态出现差异（例如用户在两次会话之间手动改过代码），以代码实际状态为准，并建议提醒用户更新本文件。

开始新任务前建议先执行一次 `pytest`、`ruff check src tests scripts`、`mypy src` 确认第 3 节记录的基线仍然成立，再继续开发。

### 这个项目上反复被验证有效的几条工作方式

以下不是通用建议，是本项目历次任务中**真实踩过坑之后**总结的，新会话照做能少走弯路：

1. **"能编译/测试通过"不等于"功能真的能用"**。本项目已出现过三次这类情况：Simulator 模式 GUI 从来没显示过数据（测试全绿，但没人调 `report_data()`）；Hardware 模式字节流拼帧缺失（Simulator 的 `LoopbackChannel` 掩盖了它）；Hardware 模式报警从未被评估（`build_hardware_runtime()` 绕开了 facade）。**凡是声称"某功能可用"，尽量实际跑一次看现象，而不是只看断言。**
2. **区分"已验证"与"仅实现"，并在汇报时明说**。用户多次强调这一点。例如 STM32 固件目前只能说"逻辑已完成并通过编译"，不能说"硬件功能已验证"。
3. **Simulator 与 Hardware 两条路径要同时检查**。`ApplicationRuntime.register_device()`（Simulator 走）与 `scripts/run_gui.py::build_hardware_runtime()`（Hardware 走，刻意绕开 facade 以读取 wire_id）是两条独立路径，任何"设备注册后要做的事"都必须两处都加——这个坑已经踩过一次。
4. **不要为了"看起来完整"而编造**。缺信息就标 `【待补充】`/`需要实物确认`；文档里的引脚、协议字段必须能追溯到 `docs/08_YINGJIAN/` 的厂商原始资料。
5. **受保护接口**（`protocol`/`communication`/`service`/`api` 的对外契约、`ui` 的 MVC 分层）改动前先说明原因并获用户同意，见第 7 节。
6. **文字类任务先出客观基线，再动手改**。去 AI 味那次（论文十章）与 2026-09-09 的一次独立验证都指向同一个结论：`humanizer-zh-academic-main` 的七条硬约束里**六条本来就合格，问题 100% 集中在正文加粗**（论文 276 处、另一次 117 处，硬上限均为 5）。**这个偏好是稳定的、可预测的**——写完长文档先数一遍加粗，比事后逐段改省得多；也不必每次都跑完整的 skill 流程去发现同一件事。

---
