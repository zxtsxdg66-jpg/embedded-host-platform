# 嵌入式设备上位机平台

> A host-side platform for embedded devices: an STM32F407 streams temperature, humidity and
> noise over a custom framed serial protocol, and a layered Python host fans the data out to a
> PyQt6 desktop app, an Android client, a browser console and the board's own LCD. A local
> language model answers questions in natural language, but never produces a number: every
> figure comes from the data layer, and each rewrite is checked before it is shown.
> Runs fully without hardware. Docs are in Chinese.

面向嵌入式设备的通用上位机平台，以「地铁站公共空间环境监测」为验证场景：
STM32F407 采集温度、湿度、噪声三个通道，经自定义帧协议上报；PC 桌面端、Android、
浏览器控制台与板载 LCD 同时呈现；本地语言模型负责自然语言问答，但**不产生任何数字**。

**在线演示**：<https://zxtsxdg66-jpg.github.io/embedded-host-platform/web/>


---

## 三个值得看的地方

**1. 串口链路：不相信字节流，只相信帧格式。**
帧头 + 长度 + CRC-32，接收端从无消息边界的字节流里拼帧、重同步。
真实开发板连续运行一小时：**3489 帧，三通道各 1163 次，丢帧 0，帧同步错误 0**。
在真实开发板的数据流上主动注入故障：15 分钟里插入 67 次杂散字节、翻转 31 次 CRC，接收器判出重同步 67 次、CRC 失败 31 次，逐项对上，没有一帧错帧被当作读数接受。

**2. 语言模型：只负责措辞，不负责事实。**
数字全部由检索层取出，模型只改写措辞；出口逐条核对改写里的每个数字能否追溯到事实，
不通过就丢弃、回退模板。意图识别在未参与调参的 148 句留出题上：规则 82.8%，
模型直接分类 91.0%，**错误执行成指令 0 次**。

**3. 分层：换数据源不动上层代码。**
数据源从软件仿真 → 虚拟串口 → 真实 STM32 逐级切换，上位机 `src/` **零改动**接通真板子。
包之间的依赖规则由测试逐文件读 import 核对，不靠自觉。

---

## 快速开始

```bash
pip install -e ".[dev]"
pytest                        # 1393 项，全部通过
ruff check src tests scripts
mypy src                      # 101 个源文件
```

不需要任何硬件，任选一种看它跑起来：

```bash
python scripts/run_gui.py                                          # 桌面界面，内置模拟设备
python scripts/run_api_server.py --mode virtual --inject-faults    # 网关 + 虚拟 STM32（带故障注入）
# 然后浏览器打开 http://127.0.0.1:8000/web/
```

Windows 下根目录的 `.bat` 可以直接双击，文件名写明了用途。全部运行方式见
[`docs/getting-started.md`](docs/getting-started.md)。

---

## 架构

```
   STM32F407 ── UART ──┐
   （或虚拟设备）        │ 字节流
                        ▼
  communication ─► protocol ─► application ─► service ─► api ─┬─► ui（PyQt6 桌面）
   通道抽象          帧/CRC      组合根与       数据、报警、      统一    └─► gateway（REST + WebSocket）
                               拼帧接收       通风、问答        门面            ├─► Android
                                  │                                           └─► web/ 浏览器控制台
                                  ├─► llm（本地模型适配）
                                  └─► storage（历史库）
```

- `ui` 与 `gateway` 是两个平级的呈现端，都只经 `api` 访问系统，互不 import
- 具体的通道、模型客户端、存储只在组合根（`application` 与 `scripts/`）里创建
- `service` 需要的外部能力以协议的形式定义在自己一侧（`LlmClient`、`HistoryStore`），不 import 适配层

详见 [`docs/architecture.md`](docs/architecture.md)。

---

## 文档

| 文档 | 内容 |
| --- | --- |
| [`docs/getting-started.md`](docs/getting-started.md) | 安装、运行模式、启动器、可选组件 |
| [`docs/architecture.md`](docs/architecture.md) | 包的划分与依赖规则、三种运行模式为什么共用一套代码、数据怎么流动 |
| [`docs/protocol.md`](docs/protocol.md) | 帧格式、CRC、命令码分配、字节流拼帧 |
| [`docs/verification.md`](docs/verification.md) | 测试策略、实测数据、故障注入、真实缺陷复盘、问答评测 |
| [`docs/decisions/`](docs/decisions/README.md) | 八个设计决策：问题、选项、取舍、实测结果 |
| [`web/README.md`](web/README.md) | 浏览器控制台 |

---

## 实测数据

| 项 | 值 |
| --- | --- |
| 一小时稳定性（真实开发板） | 3489 帧，三通道各 1163 次，丢帧 0，帧同步错误 0 |
| Modbus 应答成功率（噪声传感器） | 100%（1163 / 1163） |
| 采集周期 | 3.094 s（σ = 0.023 s；设计值 3.0 s） |
| 故障注入（虚拟设备） | 杂散字节 15 → 重同步 15；CRC 翻转 15 → CRC 失败 15 |
| 故障注入（真实开发板，15 分钟） | 杂散字节 67 → 重同步 67；CRC 翻转 31 → CRC 失败 31；错帧被接受 0 |
| 自动化测试 | Python 1393 项 + Android 41 项 |
| 意图识别（留出题 148 句） | 规则 82.8%，模型 91.0%，错误执行指令 0 次 |

原始数据在 [`experiment-data/`](experiment-data/)，统计可用
`python scripts/collect_experiment_data.py --from-csv <文件>` 复算。口径与局限见
[`docs/verification.md`](docs/verification.md)。

---

## 目录

```
src/              11 个 Python 包（分层见 docs/architecture.md）
tests/            测试，目录与 src/ 对应；另有 integration/、architecture/、scripts/
scripts/          启动器、虚拟设备、实验采集、评测与一致性检查脚本
web/              浏览器控制台（原生 JS，无构建链）
android/          Android 客户端（Kotlin）
firmware/         STM32F407 固件的自研部分
experiment-data/  实测原始数据
*.bat             Windows 双击入口
```

`firmware/` 只收录自研部分（协议、传感器驱动、Modbus、屏幕、风扇与语音告警）。
STM32 HAL、CMSIS 与开发板模板中未经修改的文件属于各自的版权方，未包含在本仓库中，
完整编译需自备对应的官方工程模板。

## 运行环境

- Python 3.10+（开发机为 3.14）
- 硬件模式：STM32F407 开发板 + AHT20 温湿度传感器 + HH_07.06 噪声传感器（Modbus RTU）
- 可选：本地 Ollama 模型（没有也能用，答案全部来自模板）；阿里云 OSS（归档上云，凭证参照 `oss_config.example.json`）
