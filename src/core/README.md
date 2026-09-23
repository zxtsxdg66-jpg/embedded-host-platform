# core

被所有包依赖、不依赖任何包的共享基础。

| 文件 | 内容 |
| --- | --- |
| `models.py` | id 类型别名（`DeviceId`、`ChannelId` 等） |
| `exceptions.py` | 跨层共享的异常基类 |
| `timestamps.py` | `now_utc()` 等时间工具。读数一律带 UTC 时间戳 |
| `channel_display.py` | 通道的中文名、单位、小数位——桌面端、网关、归档导出共用的唯一定义 |
| `link_events.py` | 串口链路事件的值类型 `LinkEvent`、`LinkStatistics` 与事件名常量 |

两处"为什么在这里"：

- **`channel_display.py`**：呈现端不止一个，而 `import ui.*` 会连带拉进 PyQt6，无界面的网关不能依赖它。
  这份映射曾在界面、网关各有一份靠人手同步，同步失败过一次（手机与桌面的小数位对不上），才收拢到这里。
  它只是展示约定，`protocol` 与 `communication` 不得据此做判断
- **`link_events.py`**：这两个类型要穿过 `api` 边界交给呈现端，而呈现端不能 import `application`。
  产生它们的 `LinkMonitor` 仍在 `application`
