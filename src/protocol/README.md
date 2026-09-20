# protocol

## 职责

`protocol` 对应 `docs/02_Architecture/System_Architecture.md` 定义的 **Protocol Layer**，实现 `docs/03_Communication/Protocol_Design.md` 中定义的通用帧协议编解码规则。

已实现（第一阶段）：

- `frame.py`：`Frame` 结构化消息（device_id/command_type/payload），字段合法性校验
- `encoder.py`：`encode(Frame) -> bytes`，具体帧格式与字段位宽见模块内文档字符串
- `decoder.py`：`decode(bytes) -> Frame`，含帧同步/长度/CRC 校验，异常输入均抛出 `protocol.exceptions` 中的具体异常，不返回残缺结果
- `exceptions.py`：`ProtocolError` 及其子类（`FrameValueError`/`FrameSyncError`/`FrameLengthError`/`ChecksumError`）

尚未实现（不在本次范围内）：

- 命令类型表的维护（命令编号与业务含义的对应关系，取决于具体设备能力描述）
- 面向任意字节流的帧同步/扫描（当前 `decode()` 假定输入恰好是一帧完整字节，流式定位由未来 `communication` 模块负责）
- Service Layer 字符串 `DeviceId` 与 Frame 数值型 `device_id` 之间的映射（桥接工作，留待后续阶段）

## 设计约束

- 与具体通信介质无关，只处理"字节流 ↔ 结构化帧"的转换
- 是 PC 与 Android 多端共享的核心契约层（详见 `docs/02_Architecture/Multi_Client_System_Architecture.md`），协议定义不允许因客户端而分叉
- 不绑定具体设备型号，命令类型与 Payload 的具体业务含义由设备能力描述定义

## 依赖关系

依赖 `core`、`communication`；被 `service` 依赖。

## 相关文档

- `docs/03_Communication/Protocol_Design.md`
- `docs/02_Architecture/Multi_Client_System_Architecture.md`
