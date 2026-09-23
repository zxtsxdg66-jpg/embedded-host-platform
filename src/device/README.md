# device

设备抽象：与具体型号、具体通信方式无关的设备模型。

| 文件 | 内容 |
| --- | --- |
| `interface.py` / `model.py` | `DeviceInterface` 与通用设备模型 |
| `capability.py` | 能力描述：有哪些通道、接受哪些命令 |
| `state.py` | 连接状态、占用状态 |
| `metadata.py` | 设备元信息 |
| `simulator.py` | `SimulatorDevice`：由可配置的数值生成器主动产生读数，simulator 模式的数据源 |
| `remote.py` | `RemoteDevice`：真实设备在上位机里的表示，只描述、**不产生任何数据**，也不碰通信 |
| `sensors/` | 温度、湿度、噪声三个模拟传感器预设 |

`RemoteDevice` 不产生数据，是有意的：真实设备的读数只能来自真实读取。
对它调用"生成读数"会被设备管理器明确拒绝。

依赖：`core`；`simulator.py` 另依赖 `service`，把生成的读数发布到数据分发服务。
