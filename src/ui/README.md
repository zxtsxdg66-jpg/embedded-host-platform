# ui

PyQt6 桌面端。MVC：

| 文件 | 角色 |
| --- | --- |
| `controller.py` | `MainController`：**`ui` 里唯一碰 `api` 的文件**。把接口调用与回调转成 Qt 信号 |
| `main_window.py` | 主窗口，组合下列部件 |
| `widgets/` | 被动视图：只通过公开方法接收数据，不 import 控制器或 `api` |
| `theme.py` | 样式表与调色板 |
| `channel_display.py` | 转导出 `core.channel_display`，保留旧的导入路径 |

`widgets/` 里的部件：顶栏、指标卡、实时曲线、统计卡、数据与历史表、设备列表、控制面板（调试用操作，默认折叠）、
通风面板（风扇模式与阈值）、风扇状态卡、问答面板。

问答面板上的"上传"按钮只在桌面端有：点击后由组合根拉起上云脚本，界面本身不碰子进程。

依赖：`api`、`core`、`service`（模型类型）、PyQt6。不依赖 `gateway`，也不被它依赖。
