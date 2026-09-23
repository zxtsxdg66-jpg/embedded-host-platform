# application

组合根与运行时：把设备、通道、协议、业务逻辑组装成一个能跑的系统。**具体的适配器只在这里（与 `scripts/`）创建。**

| 文件 | 内容 |
| --- | --- |
| `runtime.py` | `ApplicationRuntime`：持有设备管理器、数据分发、控制服务、各处理器与派发器，是 `api` 唯一的委托对象 |
| `manager.py` | `DeviceManager`：设备注册、字符串设备 id 与帧内数值设备号的映射、命令码分配、命令投递与等待应答 |
| `frame_stream.py` | `FrameStreamBuffer`：从无边界的字节流里切出完整帧——粘包、半包、脏字节重同步。接收与命令应答等待共用 |
| `hardware_runtime.py` | `HardwareDeviceReceiver`：读通道 → 拼帧 → 解码 → 过滤 → 发布读数 |
| `hardware_runner.py` / `simulator_runner.py` | 两种模式的驱动器：只提供 `run_once()`，不自己起线程，由外部循环调用 |
| `link_monitor.py` | `LinkMonitor`：接收器的可选观测点，报告每一帧与每一次异常。只听不判 |
| `fan_dispatcher.py` / `alert_dispatcher.py` / `alarm_state_dispatcher.py` / `answer_dispatcher.py` | 把决策变成设备命令：回调里只记录，轮询循环里才发送 |
| `history_recorder.py` | 读数攒批写入历史库 |
| `export_status.py` | 把上云台账的"待传数"提供给问答 |

派发器为什么拆成"记录"与"发送"两步，见 [`docs/decisions/05-dispatch.md`](../../docs/decisions/05-dispatch.md)。

驱动器不自己起线程，是为了让同一份代码能被 Qt 定时器、普通线程循环和测试以同样的方式驱动。

依赖：`core`、`device`、`protocol`、`communication`、`service`、`llm`、`storage`。
