# Web 控制台设计

> 2026-09-23 立。按 `CLAUDE.md`「修改规则」的要求，本文件先写清动机、影响范围与取舍，**确认后才实施**。
> 用户已确认全部范围（①~④）。实施进度见第 8 节。

---

## 1. 动机

毕设主体已进入维护期，余下是等导师答复。用户希望在此期间做一个 Web 前端，
一方面作为本项目的第三个呈现端，另一方面同步到开源仓库，给没有硬件、不装 PyQt 的访客一个能打开的入口。

"数据大屏"的形态被否决：一台设备、三个通道撑不起大屏，堆出来的只是装饰。
改为做一个**控制台**，重心放在本项目别处没有的两样东西上：**看得见的串口链路**与**可追溯的问答**。

## 2. 范围

| 编号 | 内容 | 动到的层 |
| --- | --- | --- |
| ① | 回放模式：前端直接读录制好的实测数据播放，无需后端，可部署到 GitHub Pages | 无（纯前端 + 一个生成脚本） |
| ② | 实时控制台：曲线、统计、报警、设备状态、历史、问答、**通风控制** | `gateway` 新增通风接口 |
| ③ | 协议检查器：逐帧显示原始字节、解出的字段、CRC 结果、重同步事件与链路计数器 | `communication`、`application`、`api`、`gateway`、`scripts` |
| ④ | 问答追溯：每一问逐层显示意图、事实清单、模板原句、模型改写与出口检查判定 | `service/assistant`、`gateway`、`scripts` |

## 3. 前端放在哪：顶级目录 `web/`

`web/` 与 `android/`、`firmware/`、`training/` 同性质：**独立工具链，不进 `pytest` 与 `mypy src` 的范围**。
它是网关的客户端，与 Android 客户端平级，只通过 REST 与 WebSocket 说话，不 import 任何 Python 符号。

**不放进 `src/gateway/static/`**：网关是无界面服务（`CLAUDE.md` 明文），Android 客户端也不在网关里面。
把页面塞进网关，等于让一个呈现端住进另一个呈现端的包里。

**由谁托管页面**：三种方式都要支持，页面代码不区分：

1. 启动脚本在网关应用上挂载 `web/` 目录（`scripts/` 里的组合逻辑，网关包本身不知道 `web/` 的存在）——浏览器打开 `http://<PC>:8000/web/` 即可，手机浏览器同样可用；
2. 直接双击 `web/index.html`，在页面里填网关地址（网关 CORS 本已放开）；
3. 不连网关，进入**回放模式**（①），数据来自 `web/replay/` 下由脚本生成的录制文件。

**不引入前端构建链**：原生 JavaScript 模块 + Canvas，无 npm、无打包。理由与答辩展示页相同——
一个需要 `npm install` 才能打开的演示，对开源访客与答辩现场都是多出来的故障点。

## 4. 网关新增的接口（②④）

全部是既有 `ApiInterface` 方法或既有数据的**直译**，写法与 2026-09-17 新增历史接口相同：

| 接口 | 对应 |
| --- | --- |
| `GET /ventilation` | `ApiInterface.get_ventilation_settings` |
| `PUT /ventilation/thresholds` | `ApiInterface.set_ventilation_thresholds` |
| `PUT /ventilation/mode` | `ApiInterface.set_fan_mode` |
| WS `fan_decision` | `ApiInterface.subscribe_fan_decision` |
| `POST /assistant/ask` 响应增加 `intent`、`facts`、`trace` 字段 | `Answer` 上已有／新增的字段（见第 6 节） |
| WS `assistant_detail` | 迟到的改写结果连同其追溯信息 |
| `GET /link/statistics`、WS `link_event` | 见第 5 节 |

**向后兼容**：REST 只增字段不改字段；WebSocket 只增消息类型。Android 客户端的 `MessageParser`
对不认识的类型返回 `Result.Unknown` 并忽略（已核对 `MessageParser.kt` 第 48 行），不受影响。

## 5. 链路监视（③）——扩展 `ApiInterface`

**现状**：原始帧与链路错误只存在于 `application/hardware_runtime.py` 的 `HardwareDeviceReceiver` 内部
（`error_count`、`ignored_frame_count`），`ApiInterface` 上没有，任何呈现端都看不到。
论文里"帧同步错误 0"是靠专用采集程序读出来的，运行中的系统自己并不展示这件事。

**做法**：

1. `application/link_monitor.py` 新增 `LinkMonitor`：记录每一帧的原始字节、解出的字段、校验结果，
   以及重同步、校验失败、忽略帧三类事件的计数；`HardwareDeviceReceiver` 接受一个可选的监视器并向它报告。
   **接收逻辑本身不变**——监视器只听，不参与判断。不传监视器时行为与现在逐字节相同。
2. `ApplicationRuntime` 持有一个 `LinkMonitor`，硬件模式的启动脚本把它交给接收器。
3. `ApiInterface` 增加 `get_link_statistics()` 与 `subscribe_link_events(callback)` 两个方法，
   `LocalApi` 直接委托给运行时。**这是本次唯一一处扩展 `ApiInterface`**，与 09-17 扩展历史查询同类。
4. 网关把它们译成 `GET /link/statistics` 与 WS `link_event`。

**仿真模式没有字节流**：`SimulatorRuntimeRunner` 直接产出数据点，不经过编码与拼帧，
所以在仿真模式下监视器始终为空，页面据实显示"当前模式没有串口字节流"。要在没有开发板时看到真实的帧，
新增第三种运行模式 `virtual`（见下）。

### 5.1 进程内虚拟 STM32

- `communication/pipe.py` 新增 `PipePair`：一对首尾相接的内存字节管道，**不保留消息边界**
  （这正是它与 `LoopbackChannel` 的区别，后者按写入块原样交付）。它是通信层的一种新实现，
  按 `CLAUDE.md` 只能在 `application` 或 `scripts` 里创建。
- `scripts/virtual_stm32.py` 抽出一个 `VirtualStm32` 类：原有逻辑不变（产生三通道数据帧、应答命令），
  但既能写真实串口（原用法），也能写管道的一端。它**依旧不 import `application`**——
  设备一侧只通过协议规范与主机一侧对齐，这条原有约定不动。
- 可选的**故障注入**：按比例把一帧拆成几次写、把几帧合成一次写、在帧间插入脏字节、翻转一个 CRC 位。
  前三种应当被帧同步机制无声地吸收，第四种应当被 CRC 检出并计数——**在页面上实时看到论文第 4 章 4.2 节
  的机制在工作**，这是本控制台区别于一般监控页面的地方。
- `scripts/run_api_server.py` 增加 `--mode virtual [--inject-faults]`，组合方式与硬件模式相同，
  只是把 `SerialChannel` 换成管道的主机端。从 `DataService` 往上，三种模式代码完全一致。

## 6. 问答追溯（④）——改动 `service/assistant`

**这是风险最高的一处**：它是论文第 4 章 4.5 节描述的核心，有问答基线可对照。原则是**只增加可见性，不改变任何判定**。

1. `phrasing.py`：把 `choose()` 里的五道检查抽成 `judge()`，返回"采用哪句、来源、判定代码"三元组；
   `choose()` 改为调用 `judge()` 并丢掉判定代码。**两者对任何输入给出相同的文本与来源**，
   由一组逐项对照的测试保证。
2. `models.py`：新增 `RephraseAttempt`（模板原句、模型原文、判定代码）与 `Answer.trace`
   （可选，默认 `None`，按尝试顺序记录，含重试）。
3. `assistant.py`：`_finish_rephrasing()` 在调用 `judge()` 时顺带把每次尝试记进 `trace`。
4. `scripts/automation_wiring.make_poll_once` 增加可选参数 `on_assistant_detail`，把完整的 `Answer`
   交给网关；原有的 `(text, source)` 回调不变，桌面端不受影响。

**为什么不违反第 4 章的约束**：追溯信息是对已经发生之事的只读记录，模型没有因此多拿到任何输入或权力；
页面显示的模型原文，正是出口检查已经拒绝或采纳过的那一句。

**基线**：判定逻辑不变，因此不影响问答基线；按维护期规则，改动后仍以不接模型的规则层基准
（`assistant_benchmark.py --no-llm`）复核一次，逐项与改动前一致才算完成。

## 7. 回放模式（①）

`web/tools/build_replay.py` 从 `docs/07_Thesis/实验数据/` 与 `docs/05_Test/baseline/` 读原始记录，
生成 `web/replay/*.json`：一小时稳定性实验的全部帧、阶跃与报警实验、三套问答题库、约束实录。
前端在回放模式下按时间轴把这些数据"重新推送"一遍，走与实时模式**同一套**渲染代码。
开源仓库的 GitHub Pages 部署的就是这个模式，访客打开链接即可看到一小时的真实数据在控制台上重演。

## 8. 实施顺序与进度

| 步骤 | 内容 | 状态 |
| --- | --- | --- |
| 1 | 本设计文档；同步修改 `CLAUDE.md`、`Software_Structure.md`、`docs/README.md` | 完成 |
| 2 | 网关通风接口（②） | 完成 |
| 3 | 问答追溯（④） | 完成 |
| 4 | 管道、链路监视、虚拟设备与 `virtual` 模式（③） | 完成 |
| 5 | `web/` 控制台（实时 + 回放） | 完成，浏览器实测见下 |
| 6 | 测试、文档、三项检查；同步到开源仓库 `embedded-host-platform`（推送前由用户确认） | 本仓库完成；开源仓库同步待用户确认后推送 |

浏览器实测（2026-09-23，`run_api_server.py --mode virtual --inject-faults` + `/web/`）：实时徽标显示 `virtual+faults`；串口链路页计数随帧增长，CRC 失败帧的拆解同时给出声明 CRC 与浏览器重算的 CRC-32，二者不同；在线提问后模型结果经 WebSocket 迟到补送，追溯区显示"采纳"。回放模式（双击 `index.html`）三段均可播放：一小时实验 3489 帧；故障注入会话注入拆帧 33、并帧 18、杂散字节 15、翻转 15，主机侧判出重同步 15、CRC 失败 15、正常帧 165；问答实录中"屋里热吗"首次改写因添加建议措辞被拦、重试后采纳。

## 9. 不做的事

- 不做登录与权限：网关仍按局域网可信环境设计（见 `src/gateway/server.py` 文件头）。暴露到公网之前须另行设计。
- 不做数据大屏的装饰性组件（地图、翻牌器、3D）。
- 不让网页直接连串口（Web Serial API）：那会绕过整个分层，让呈现端感知底层通信方式，违反 `CLAUDE.md`。
