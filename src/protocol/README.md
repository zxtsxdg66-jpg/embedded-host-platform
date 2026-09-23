# protocol

帧结构与编解码，与通信介质无关。格式规范见 [`docs/protocol.md`](../../docs/protocol.md)。

| 文件 | 内容 |
| --- | --- |
| `frame.py` | `Frame`：设备号、命令码、载荷，构造时校验取值范围 |
| `encoder.py` | `encode(Frame) -> bytes`。帧格式常量（帧头、字段宽度、字节序）的权威定义 |
| `decoder.py` | `decode(bytes) -> Frame`，校验帧头、长度、CRC-32；失败抛具体异常，不返回残缺结果 |
| `exceptions.py` | `FrameSyncError`、`FrameLengthError`、`ChecksumError` 等 |

`decode()` 只解析**恰好一帧**的字节。在无边界的字节流里找帧边界不是它的职责，
那是 `application/frame_stream.py` 的事。

依赖：`core`。
