# service

业务逻辑。不碰物理资源：不开串口、不连网络、不写磁盘——需要这些能力时，在这里定义协议，由组合根注入实现。

| 文件 | 内容 |
| --- | --- |
| `data_models.py` / `command_models.py` | `DataPoint`、`Command`、`CommandResult` |
| `data_service.py` / `data_service_impl.py` | 读数的订阅与分发（进程内、同步） |
| `control_service.py` / `control_service_impl.py` | 控制权（"共享读、独占写"）与命令派发；派发经注入的 `CommandTransport` |
| `sensor_data_processor.py` | 每个通道的统计（当前/最小/最大/平均）与阈值报警。阈值只在这里定义一份 |
| `ventilation_controller.py` | 通风决策：自动模式按可调阈值判断风扇该开该关；手动模式直接给定 |
| `alarm_announcer.py` | 什么时候该把报警念出来：连续确认（拒绝单个尖峰）+ 冷却（打断声学反馈） |
| `history.py` | `HistoryStore` 协议与 `HistoryPoint`；存储实现在 `storage` |
| `assistant/` | 问答管线，见下 |

报警阈值与通风阈值是**两套**：报警阈值依据国家标准论证、固定不变（湿度是双向的，低于 30 或高于 75 %RH 都报警）；
通风阈值可以在运行时调，只看上限（高于才开风扇）。两者分开，调通风不会动到报警的依据。

## `assistant/`

三层管线：意图识别 → 取数 → 措辞。设计见 [`docs/decisions/02-llm.md`](../../docs/decisions/02-llm.md)。

| 文件 | 内容 |
| --- | --- |
| `intent.py` | 规则识别：关键词表与句式，复合句拆分，征询语气守卫 |
| `parsing.py` | 模型分类的提示词与输出解析（只接受一个标签） |
| `retrieval.py` | 取数：读统计与通风状态，产出结构化的 `Facts`。**全管线唯一产生数字的地方** |
| `phrasing.py` | 模板与出口检查（接地、越限断言、凭空判断、建议措辞、长度） |
| `control.py` | 指令白名单与执行；数值由正则从原话里取 |
| `assistant.py` | 编排：规则优先、模型复核指令、改写与重试、反问与确认 |
| `models.py` | `Intent`、`Facts`、`Answer`、`CheckVerdict` 等 |
| `llm_port.py` / `export_status_port.py` | 需要外部提供的能力：模型客户端、上云台账的待传数 |

依赖：`core`、`device`（通道名常量）。不依赖 `llm` 与 `storage`。
