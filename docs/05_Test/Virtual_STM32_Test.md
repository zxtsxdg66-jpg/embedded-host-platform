# Virtual STM32 验证工具

## 文档定位

本文档说明 `scripts/virtual_stm32.py`——一个**在没有真实 MCU 的情况下、通过真实串口字节流验证 Hardware Mode 完整收发链路（数据上行 + 命令下行）**的工具。它比 mock/回环测试更进一步：不是在内存里伪造 `receive()` 的返回值，而是像真实 STM32 一样，把按 `Protocol_Design.md` 帧格式编码好的字节，实实在在地写到一个 OS 串口设备上，让运行中的 `scripts/run_gui.py --mode hardware` 通过真实的 `SerialChannel` 读到；反过来也会真正监听并应答 GUI 下发的命令帧，而不是单向只发数据。**2026-08-12 已通过 WSL2 + socat 虚拟串口对完整验证两个方向都能跑通**，详见 `docs/05_Test/status/早期归档.md`（2026-09-09 前为 `Project_Status_Context.md` 第 10 节）。

## 数据上行

```
scripts/virtual_stm32.py                          scripts/run_gui.py --mode hardware
（"虚拟 STM32" 进程）                                （真实 GUI 进程）

TemperatureSensorSimulator/                        SerialChannel.receive()
HumiditySensorSimulator/                                   │
NoiseSensorSimulator                                        ▼
  .generate(channel).value                          protocol.decode()
        │                                                   │
        ▼                                                   ▼
protocol.encode(Frame(                              HardwareDeviceReceiver
  device_id=<--device-id>,                            ._process_frame()
  command_type=DATA_REPORT_CODE,                              │
  payload=JSON{"channel","value"}                             ▼
))                                                    DataService.publish()
        │                                                     │
        ▼                                                     ▼
SerialChannel.send()                                SensorDataProcessor / UI
        │                                          （与 Simulator 模式完全相同的下游代码）
        ▼
   COM4（虚拟串口对的一端）
        │
   ═══════════════ 虚拟串口对（com0com 等）／真实串口线 ═══════════════
        │
   COM3（虚拟串口对的另一端）
```

## 命令下行

每轮发送完 temperature/humidity/noise 三帧后，`virtual_stm32.py` 不是简单 `sleep(interval)`，而是调用 `_drain_and_ack_commands()`：在同样长度的时间窗口内持续监听是否有命令帧到达，一旦收到就立即回复 `COMMAND_ACK_CODE` 帧，让 GUI 的"发送命令"能收到真实设备的应答，而不只是 Simulator 模式下 `LoopbackChannel`/`DeviceManager` 自问自答那一套。

```
scripts/run_gui.py --mode hardware                 scripts/virtual_stm32.py
（真实 GUI 进程，用户点击"发送命令"）                    （"虚拟 STM32" 进程）

DeviceManager.deliver()                             _drain_and_ack_commands()
  ._await_device_ack()                                循环 channel.receive()
        │                                                     │
        ▼                                                     ▼
protocol.encode(Frame(                              _extract_frame() 拼帧
  command_type=<业务命令编码>                                  │
))                                                             ▼
        │                                            protocol.decode()
        ▼                                                     │
SerialChannel.send() ──────────────────────────────▶  匹配 device_id 后
                                                        构造 ack Frame(
                                                          command_type=COMMAND_ACK_CODE,
                                                          payload=JSON{"status":"success"}
                                                        )
        ▲                                                      │
        │                                                      ▼
FrameStreamBuffer 拼帧后 decode() ◀────────────────── SerialChannel.send()
        │
        ▼
CommandResult（SUCCESS/FAILED，或超时后
  api.exceptions.CommandDeliveryError）
```

`virtual_stm32.py` 接受任意命令类型（不区分 PING/RESET 等，一律回复 `success`）——它没有 Simulator 模式 `registration.accepted_commands` 那种"设备允许哪些命令"的概念，真实固件应当自行决定接受/拒绝哪些命令类型。

两个进程之间**只共享协议规范，不共享代码**——`virtual_stm32.py` 里 `DATA_REPORT_CODE = 0x01`/`COMMAND_ACK_CODE = 0x02` 都是硬编码的字面量，而不是从 `src/application/manager.py` import 来的，这是刻意为之：真实 STM32 固件也只能在 C 代码里硬编码这些值，`virtual_stm32.py` 在这一点上应该表现得和真实固件一样。同样的原因，脚本里解析字节流、切出一帧的 `_extract_frame()` 也是独立实现的一份最小逻辑，没有 import `src/application/frame_stream.py`（PC 侧 `HardwareDeviceReceiver`/`DeviceManager` 共用的拼帧工具）——真实固件同样得在 C 里自己写这段逻辑，不能"共享 Python 代码"。

## 进程内使用与故障注入（2026-09-23）

循环逻辑已移入 `VirtualStm32` 类，它面向任意 `CommunicationChannel`：可以是上文的真实串口，也可以是 `communication.pipe.make_pipe_pair()` 的设备端。`scripts/run_api_server.py --mode virtual` 用的是后者，因此**不需要 com0com 或 socat**，主机侧的真实接收链路照样全程运行，启动方式见 [`Runtime_Mode.md`](Runtime_Mode.md)。

`FaultPlan` 让它故意出错，每一项是一个概率：

| 字段 | 默认（`--inject-faults`） | 做什么 | 主机侧应有的反应 |
| --- | --- | --- | --- |
| `split` | 0.25 | 把一帧拆成两次写入 | 静默拼回，不计错 |
| `merge` | 0.3 | 把一轮三帧粘成一次写入 | 静默切开，不计错 |
| `garbage` | 0.1 | 在帧前插入几个杂散字节 | 重同步一次（`resync`） |
| `bitflip` | 0.03 | 翻转帧尾 CRC 的一个比特 | CRC 失败一次（`checksum_error`），该帧丢弃 |

`VirtualStm32.injected` 记录实际注入的次数。给定 `seed` 时注入与传感器读数都可复现，`scripts/build_web_replay.py` 据此生成回放里的故障注入会话，并断言主机侧判出的重同步数、CRC 失败数与注入数**逐一相等**。命令行版本同样支持 `--inject-faults`。

## 如何启动虚拟设备

### 前置条件：一对相互连通的串口

由于本机没有真实硬件，需要先在操作系统层面建立一对"虚拟串口对"（写入一端、能从另一端读到），常见方式：

- **Windows**：安装 [com0com](https://sourceforge.net/projects/com0com/)（开源虚拟串口驱动，与 Python/pyserial 无关，是系统级工具，不属于本项目依赖），创建一对端口，如 `COM3 <-> COM4`
- **Linux/WSL**：`socat -d -d pty,raw,echo=0,link=/tmp/ttyV0 pty,raw,echo=0,link=/tmp/ttyV1` 创建一对虚拟串口
- 也可以用两块真实 USB 转串口模块，用杜邦线把 TX/RX/GND 直接对接，效果等价（但这就已经不是"没有真实硬件"的场景了）

### 启动虚拟 STM32 进程

```bash
python scripts/virtual_stm32.py --port COM4
```

可选参数：

```bash
python scripts/virtual_stm32.py --port COM4 --device-id 1 --baudrate 115200 --interval 2.0
```

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--port` | 无（必填） | 虚拟串口对中，本进程写入的一端，如 `COM4` |
| `--device-id` | `1` | 写入每一帧的数值型设备 ID（`Frame.device_id`，0-255），**必须**与 GUI 侧 `HardwareDeviceReceiver` 期望的 wire id 一致（见下一节） |
| `--baudrate` | `115200` | 波特率，需与 GUI 侧 `--baudrate` 一致（本项目用的是应用层帧格式，不是真的按波特率解析数据，但保持配置一致是好习惯） |
| `--interval` | `2.0` | 每轮发送 temperature/humidity/noise 三帧之间的间隔秒数；这段时间也是 `_drain_and_ack_commands()` 监听并应答命令帧的窗口长度（每 0.1 秒检查一次），因此命令的应答延迟通常远小于这个值，不需要额外配置 |

启动后会持续打印发送日志（`[virtual-stm32] sent temperature=25.51` 等），`Ctrl+C` 可优雅停止（会调用 `channel.disconnect()`）。

## 如何连接 GUI Hardware 模式

在**另一个终端**启动 GUI，`--port` 填虚拟串口对的**另一端**：

```bash
python scripts/run_gui.py --mode hardware --port COM3
```

或双击 `run_gui_模拟数据界面.bat --mode hardware --port COM3`。

**关于 device_id 的一致性**：GUI 侧 `scripts/run_gui.py` 的 `build_hardware_runtime()` 内部通过 `runtime.devices.register(...)` 给注册的 `RemoteDevice` 自动分配 wire id——由于每次 `--mode hardware` 启动时只注册这一个设备，该 wire id 固定为 `1`（`DeviceManager` 的 `_next_wire_id` 从 1 开始计数）。因此 `virtual_stm32.py` 保持默认的 `--device-id 1` 即可与之匹配，不需要额外配置；如果未来 GUI 侧同时注册多个 Hardware 设备，则需要相应调整这里的 `--device-id`。

## 相关文档

- `docs/03_Communication/Protocol_Design.md`（帧格式规范）
- `docs/05_Test/Hardware_Simulation_Mode.md`（Simulator/Hardware 双模式架构）
- `docs/05_Test/Runtime_Mode.md`（`run_gui.py` 启动参数总览）
- `docs/05_Test/Project_Status_Context.md`（项目整体状态归档）
