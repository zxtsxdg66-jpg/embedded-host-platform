# communication

## 职责

`communication` 对应 `docs/02_Architecture/System_Architecture.md` 定义的 **Communication Layer**，负责与具体通信介质的字节收发，向上（`protocol`）提供统一的字节流读写接口。

已实现（第一阶段）：

- `interface.py`：`CommunicationChannel` 抽象接口（`connect`/`disconnect`/`send`/`receive`/`is_connected`）
- `loopback.py`：`LoopbackChannel`，基于内存队列的回环实现，用于无真实硬件时的软件验证
- `exceptions.py`：`CommunicationError` 及其子类

已实现（第二阶段）：

- `serial.py`：`SerialChannel` —— 基于 [pyserial](https://pyserial.readthedocs.io/) 的真实 UART/USB 串口实现，第一个非模拟的 `CommunicationChannel`
- `exceptions.py` 新增：`SerialPortNotFoundError`（串口不存在）/ `SerialConnectionError`（连接失败）/ `SerialReadTimeoutError`（读取失败或超时）/ `SerialWriteError`（写入失败或超时）—— pyserial 自身的异常在本模块边界被统一转译，调用方无需 import `pyserial`

已实现（2026-09-23，Web 控制台的 `virtual` 运行模式）：

- `pipe.py`：`PipeChannel` 与 `make_pipe_pair() -> (host_end, device_end)`：两个背靠背的内存通道端，相当于一根不存在的零调制解调器线。**与 `LoopbackChannel` 的区别正是它存在的理由**：回环把每次 `send()` 原样作为一次 `receive()` 交回，保留了消息边界，而真实串口没有这个性质（论文第 5 章 5.3 节，这曾让四个缺陷在 Simulator 模式下藏住）；管道一端的 `receive()` 返回已到达的**全部**字节，不论分几次写入，所以帧会粘连，拆开写会出现半帧。线程安全（虚拟设备在自己的线程写，主机在驱动线程读）。与其它具体通道一样**只能在 `application` 或 `scripts` 中创建**。设计见 `docs/02_Architecture/Web_Console_Design.md` 第 5.1 节

尚未实现（不在本次范围内）：

- USB（作为独立通信方式，区别于 USB 转串口场景）、TCP-IP、蓝牙等其他真实通信方式（详见 `docs/03_Communication/Communication_Design.md`）
- 异步/事件驱动收发、`on_data_received`/`on_state_changed` 等回调式状态通知
- 连接生命周期的自动重连

## 设计约束

- 不解析数据内容，只负责可靠的字节传输
- 各通信方式必须实现同一套抽象接口，`protocol` 与 `service` 不感知具体通信方式
- 异步非阻塞，连接状态必须可被上层观测

> 具体通信方式的子模块划分（如 uart/usb/tcpip/bluetooth）将在实现阶段按 `docs/02_Architecture/Software_Structure.md` 的建议目录结构逐步细化，本次初始化仅建立顶层模块骨架。

## 依赖关系

依赖 `core`；被 `protocol` 依赖。不依赖 `device`、`service`、`api`、`ui`。

## 相关文档

- `docs/03_Communication/Communication_Design.md`
- `docs/02_Architecture/System_Architecture.md`
