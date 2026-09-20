# 运行模式说明（Simulator / Hardware）

## 文档定位

**本文档只回答"怎么启动"**：用哪个启动器、加什么参数、COM 口怎么配。
两种模式在架构上有什么不同、为什么能共用同一套上层代码，见
[`Hardware_Simulation_Mode.md`](Hardware_Simulation_Mode.md)——那份回答"为什么"，
本文档不再重复链路图与分层说明。

## 七个启动器该用哪个

| 启动器 | 用途 | 模式 |
| --- | --- | --- |
| `run_gui_模拟数据界面.bat` | 只要 PC 界面 | 默认 Simulator，`--mode hardware` 切硬件 |
| `run_gui_hardware_真实硬件界面.bat` | 只要 PC 界面，交互式选串口 | Hardware |
| `run_api_server_手机网关.bat` | 只要网关（无界面，供手机连） | 两种都支持 |
| `run_all_界面加网关.bat` | **界面 + 网关同进程**，PC 与手机同时看 | 两种都支持 |
| `collect_data_实验数据采集.bat` | 论文数据采集，边跑边存 CSV | Hardware |
| `start_llm_启动本地模型.bat`（2026-09-10 移到根目录） | 拉起本地 Ollama 并**发一次真实请求预热**模型；`--check` 只探测 | 与模式无关 |
| `stop_llm_停止本地模型.bat`（2026-09-10 新增） | 卸载模型、释放约 3 GB 内存，服务保留；`--server` 连服务与托盘程序一起停，`--status` 只看 | 与模式无关 |

后两个只管本地语言模型，不启动上位机本身。`scripts/start_llm_启动本地模型.bat` 是 `start_llm_启动本地模型.bat` 的旧入口，仍可用。

**答辩演示用 `run_all_界面加网关.bat`。** 它是唯一同时接了界面、网关、四项自动化
（通风/语音/报警位图/问答上屏）与本地语言模型的启动器。

> **环境问答与模型**：`run_all.py` 与 `run_api_server.py` 都会在启动时探测一次本地
> Ollama，探测不到就打印一行说明并继续——问答照常工作，只是措辞不经改写。
> 想显式关掉加 `--no-llm`，想换模型加 `--llm-model <名字>`。
> 演示前先双击 `start_llm_启动本地模型.bat`：模型冷启动首次推理要从磁盘载入约 3.4 GB（实测 8.8 s），
> 预热能把这段等待挪到开场之前。用完双击 `stop_llm_停止本地模型.bat` 释放内存——`OLLAMA_KEEP_ALIVE = -1`
> 下模型不会自己卸载。原理见 [`LLM_Boundary.md`](../02_Architecture/LLM_Boundary.md) 第七节。

## 如何启动模拟模式（Simulator 模式）

不需要任何真实硬件，双击或命令行均可：

```bash
python scripts/run_gui.py
# 等价于：
python scripts/run_gui.py --mode simulator
```

或双击项目根目录的 `run_gui_模拟数据界面.bat`（不带参数即为模拟模式）。

启动后会自动注册**三个环境传感器模拟设备**，与 Hardware 模式上报的通道完全一致：

| 设备 id | 通道 | 数值特征 |
| --- | --- | --- |
| `sim-env-1-temp` | `temperature` | 20~40℃，平滑随机游走 |
| `sim-env-1-humi` | `humidity` | 40~80%，变化更缓慢 |
| `sim-env-1-noise` | `noise` | 40~60dB 基线 + 短时峰值 |

数据由 `SimulatorRuntimeRunner` 驱动，每秒生成一轮，界面上的指标卡片、实时数据表、
实时曲线、统计信息、阈值报警都会真实工作——**Simulator 模式因此可以作为没有硬件时
的完整替代演示手段**，而不只是"能打开窗口"。

在界面中选中设备、在"通道 ID"下拉框里选 `temperature`/`humidity`/`noise` 点"订阅"，
即可看到数据流入；也可以发送 `PING` 命令验证控制链路。

> **历史沿革**：2026-08-15 之前，Simulator 模式注册的是通用演示设备（`ch1`/`ch2`），
> 且**没有任何东西驱动数据生成**——`report_data()` 只有测试在调用，因此实际启动 GUI
> 后界面永远是空的（已实测确认）。同日修复：新增 `application/simulator_runner.py`
> 并在 `scripts/run_gui.py` 里用 QTimer 驱动，同时把演示设备换成上述三个环境传感器，
> 使两种模式的界面表现一致。

## 如何启动硬件模式（Hardware 模式）

### 方式一：双击 `run_gui_hardware_真实硬件界面.bat`（推荐，不用记串口号）

启动后会自动扫描当前所有串口并列出来，标注出**可能是开发板**的那个（按硬件 id 里
是否含 CH340/CP210/FTDI 等 USB 转串口特征判断，并排除蓝牙虚拟串口），选编号回车即可：

```
检测到以下串口：

  [1] COM3     标准串行over蓝牙链接
  [2] COM7     USB-SERIAL CH340  <-- 可能是开发板

请选择串口编号（直接回车 = COM7）:
```

之所以不做成"自动选唯一的串口"：很多 Windows 机器在**没插任何板子**时就已经有串口了
（本项目开发机上就有 COM3/COM4 两个蓝牙虚拟串口）。自动选第一个会选错，然后表现为
莫名其妙的超时，比直接报错更难排查。

也可以带参数运行，跳过选择：

```bat
run_gui_hardware_真实硬件界面.bat --port COM7
run_gui_hardware_真实硬件界面.bat --baudrate 9600
```

若串口打不开（板子被拔掉、串口被串口助手占用等），会给出中文提示而不是 Python 堆栈。

### 方式二：命令行直接指定

需要指定串口号：

```bash
python scripts/run_gui.py --mode hardware --port COM3
```

可选参数：

```bash
python scripts/run_gui.py --mode hardware --port COM3 --baudrate 115200 --device-id mcu-1
```

或通过 `run_gui_模拟数据界面.bat` 转发参数（`.bat` 会将其收到的所有参数原样传给 `run_gui.py`）：

```bat
run_gui_模拟数据界面.bat --mode hardware --port COM3
```

> 注意 `run_gui_模拟数据界面.bat` **双击**等于不带参数，那是模拟模式；硬件模式要么在终端里带参数
> 调用它，要么直接双击上面介绍的 `run_gui_hardware_真实硬件界面.bat`。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--mode` | `simulator` | `simulator` 或 `hardware` |
| `--port` | 无（hardware 模式下必填） | 串口设备名，如 Windows 下的 `COM3`，Linux 下的 `/dev/ttyUSB0` |
| `--baudrate` | `115200` | 波特率，需与 MCU 固件配置一致 |
| `--device-id` | `mcu-1` | 界面中显示的设备 ID，与固件侧无强制绑定关系，仅用于 PC 侧标识 |

若省略 `--port` 却指定了 `--mode hardware`，脚本会在启动前直接报错退出（`argparse` 参数校验），不会尝试用一个空端口号打开串口。

## 要 PC 界面与手机同时看数据：用 `run_all_界面加网关.bat`

**硬件模式下不能同时双击 `run_gui_hardware_真实硬件界面.bat` 和 `run_api_server_手机网关.bat`。** 串口是独占资源，先启动的那个占住 COM 口，后启动的会直接失败：

```
SerialConnectionError: failed to open serial port 'COM10':
PermissionError(13, '拒绝访问。')
```

一块板子、一根线，就只能有一个读取者。所以两端同时要数据时，用**一个进程同时承载两个消费方**：

```bat
run_all_界面加网关.bat
```

双击后会依次问运行模式、串口，并打印手机要填的 IP，然后打开 PC 界面；网关在后台线程上同时提供 REST + WebSocket。命令行等价写法：

```bash
python scripts/run_all.py --mode hardware --port-serial COM10
python scripts/run_all.py                     # 模拟模式，不需要硬件
```

注意两个"port"参数不同名，避免混淆：`--port` 是网关的 HTTP 端口（默认 8000），`--port-serial` 是 STM32 的串口。

关闭 PC 界面窗口即同时停止网关。

**什么时候仍然用单独的启动器**：只看 PC 界面用 `run_gui_hardware_真实硬件界面.bat`，只给手机供数用 `run_api_server_手机网关.bat`——少跑一个消费方，排障时干扰更少。模拟模式下两个脚本可以各跑各的（各自生成模拟数据，不争串口）。

数据只被解码一次、发布一次，再扇出给界面与手机，所以这种方式**不比单开一个慢**。实现与线程模型见 `scripts/run_all.py` 的模块 docstring 与 `docs/05_Test/Project_Status_Context.md` 第 4 节"单串口双消费方"。

## COM 口如何配置

1. **确认真实串口号**：在 Windows 的"设备管理器 → 端口 (COM 和 LPT)"中查看 MCU/USB 转串口芯片被系统分配的端口号（如 `COM3`），或使用 `python -m serial.tools.list_ports`（`pyserial` 自带命令行工具）列出当前系统所有可用串口
2. **将该端口号传给 `--port` 参数**，如 `--port COM3`
3. **波特率必须与 MCU 固件配置一致**，通过 `--baudrate` 指定，默认 `115200`
4. **端口不存在时的行为**：`communication/serial.py` 的 `SerialChannel.connect()` 会先枚举系统当前可用端口，若 `--port` 指定的端口不在其中，会抛出 `SerialPortNotFoundError` 并使程序以非零退出码结束，不会静默失败或卡死；端口存在但无法打开（被占用/权限不足）则抛出 `SerialConnectionError`
5. **当前无需 MCU 真实连接即可测试**：所有涉及串口交互的自动化测试均使用 `mock`（替换 `pyserial` 的 `Serial` 构造函数），因此不需要真实接上开发板即可验证 `--mode hardware` 这条链路的组装是否正确；但**实际读取到真实数据**仍然需要真实硬件在另一端按 `docs/05_Test/Hardware_Simulation_Mode.md` 描述的帧格式发送数据

## 相关文档

- `docs/05_Test/Hardware_Simulation_Mode.md`（两种模式的架构设计与数据流）
- `docs/05_Test/Project_Status_Context.md`（项目整体状态归档）
- `src/application/hardware_runner.py`（`HardwareRuntimeRunner` 的轮询驱动设计）
