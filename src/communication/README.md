# communication

字节收发。向上只提供 `connect` / `disconnect` / `send` / `receive`，不关心字节的含义。

| 文件 | 内容 |
| --- | --- |
| `interface.py` | `CommunicationChannel` 抽象 |
| `serial.py` | `SerialChannel`：基于 pyserial 的真实串口。pyserial 的异常在这里转译成本包的异常族，调用方不必 import pyserial |
| `loopback.py` | `LoopbackChannel`：内存回环，simulator 模式用。**保留消息边界**：一次 `send()` 对应一次 `receive()` |
| `pipe.py` | `make_pipe_pair()`：一对背靠背的内存通道，**不保留消息边界**——`receive()` 返回已到达的全部字节。virtual 模式用它把虚拟设备接到真实接收器上 |
| `exceptions.py` | `SerialPortNotFoundError`、`SerialConnectionError` 等 |

回环与管道的区别是这个包里最重要的一件事，见 [`docs/decisions/01-simulation.md`](../../docs/decisions/01-simulation.md)。

**具体通道只能在 `application` 或 `scripts/` 里创建**，呈现端不得知道当前用的是哪种通道。

依赖：`core`。
