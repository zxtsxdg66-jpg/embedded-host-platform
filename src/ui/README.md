# ui

## 职责

`ui` 对应 `docs/02_Architecture/System_Architecture.md` 定义的 **UI Layer**，在多端架构（`docs/02_Architecture/Multi_Client_System_Architecture.md`）中具体为 **PC Presentation（PyQt6）** 的实现。

已实现（截至 2026-08-14，经历了第二阶段基础实现 → 阈值报警/统计信息接入 → 界面整体美化/产品级视觉重构/信息层级优化 → GUI 背景视觉层+面板半透明化 四轮迭代，详细过程见 `docs/05_Test/Project_Status_Context.md` 第 2 节 UI Layer）：

- `controller.py`：`MainController(QObject)` —— MVC 中的 Controller，唯一 import `api` 的文件，将 `ApiInterface` 调用结果（含 `subscribe_alarm_status`/`subscribe_statistics` 两个全局订阅）转换为 Qt 信号
- `main_window.py`：`MainWindow(QMainWindow)` —— MVC 中的 View，组合下述 widgets 形成深色工业监控风格的仪表盘布局：`BackgroundWidget` 作为 `central`，其上为顶部信息栏，再下为**状态横幅 + 一个两页的 `QStackedWidget`**（2026-09-18）：
  - **第 1 页「实时监控」**：关键指标卡（温度/湿度/噪声/风扇）、实时曲线、实时数据表+统计信息、活动日志+环境问答+通风与调试控制
  - **第 2 页「历史记录」**：**每条通道一列**、各自独立滚动（2026-09-18），每列为「接收时间/数值/状态」三小列，列标题写明通道、单位与供数设备。**刻意不按时刻并成一张表**——三通道不同时到达（一轮约 3.09 s，轮内相差几百毫秒），对齐后一旦丢帧就会把第 N 轮的温度与第 N+1 轮的湿度排进同一行，每个数都真、所属时刻却错，且界面上看不出来；显示上限也改为**每列各算各的**
  - 状态横幅**在两页之外**、两页共用——系统状态要能一眼看见，不该随翻页消失
  - 翻页入口是顶部栏的两个页签（`TopBarWidget.page_selected`）与 `Ctrl+1`/`Ctrl+2`，都汇到 `MainWindow.show_page()` 一处，避免快捷键翻了页而页签还标着旧页。**翻页纯属 View 内部的事**：没有加 controller 信号，也没有加 `api` 方法
  - 为什么分页：历史表原先在底部行左下角，按 stretch 折算只有约 9% 的仪表盘面积，而它是一张五列表；同行另外三块也都要空间，加宽是零和。做法与板载 LCD 分两页同源，但代价低得多——协议、固件、`api`/`service` 一处未动
  - **翻到第 2 页不重新查库**：实时链路一直在往表里追加，而 `DataPanelWidget.prefill_history()` 是追加语义，翻一次查一次会把已存的行复制一遍
- `theme.py`：应用级 QSS 样式表 + 匹配的 `QPalette`（`apply_theme(app)`，由 `scripts/run_gui.py` 在构造 `QApplication` 后立即调用一次，符合 `pyqt6-ui-development-rules` skill Iron Law 3）；集中定义颜色常量、字号排版类（`set_class`/`set_state` 动态属性）、面板半透明度分档常量、背景图像相关配置（`BACKGROUND_IMAGE`/`BACKGROUND_OVERLAY_OPACITY` 等）
- `channel_display.py`：`channel_label()`/`channel_unit()`/`channel_decimals()`/`format_value()` —— channel id → 中文名/单位/**小数位**的唯一权威映射（UI 展示层约定，仅覆盖当前三个已知传感器 channel，不进入 `protocol`/`communication`）。小数位按通道定（2026-09-18）：温度、噪声 2 位，**湿度 0 位**（AHT20 湿度精度 ±2 %RH，多写小数即虚假精度）；**未登记的通道原样输出、不重新格式化**——取整的理由来自知道传感器精度，对没听说过的通道并不成立。**取整只发生在显示这一步**，存储/问答/上云用的仍是原值。指标卡与两张表共用这一个函数（指标卡 2026-09-18 起由写死的 `.1f` 改过来），手机端 `ChannelFormat` 同日统一到同一口径，**两端必须一起改**
- `widgets/`：与业务逻辑解耦的"被动视图"（Passive View）组件，均不 import `controller`/`api`，只通过公开 setter 方法接收数据、只通过 Qt 信号表达用户操作
  - `background_widget.py`：`BackgroundWidget` —— `MainWindow` 的 `central` widget，`paintEvent` 中以 cover 方式绘制自适应裁剪的背景图 + 半透明遮罩（`cover_source_rect()` 抽成纯函数，独立于 Qt 对象，便于测试）
  - `chart_widget.py`：`ChartWidget` —— 基于 `QPainter` 的滚动多序列折线图，含网格线/坐标轴数值/图例，公开接口仍仅 `add_point(series: str, value: float)`/`clear()`/`series_names()`，不了解 `DataPoint`/`Command` 等业务类型；颜色取自 `theme.py` 的调色板常量，绘图区背景为半透明填充
  - `top_bar.py`：`TopBarWidget` —— 标题/当前设备/连接指示灯/运行模式标签（纯展示字符串，由调用方传入）/时钟
  - `fan_card.py`：`FanCardWidget` —— 2026-09-07 新增，通风风扇状态卡，作为**第四张指标卡**与温度/湿度/噪声并排（复用同一个 `metricCard` objectName 以继承卡片样式）。放在指标行而非控制区，是为了让"因"（温湿度读数）和"果"（风扇状态+触发原因）在同一行上一眼可读。只读；刻意不继承 `MetricCardWidget`——那个控件整套接口都是数值型的（`update_value(value: float)` + 由前后两个数字算出的趋势箭头），而风扇有状态没有量值，继承等于继承一套无法诚实实现的接口。新增 `state="running"` 视觉状态（绿色描边），不复用 `warning`/`alarm`——风扇转起来是系统在正常履行职责，用告警色会误导
  - `ventilation_panel.py`：`VentilationPanelWidget` —— 同日新增，通风**控制**（与上面的状态卡分处两地）：可运行时调整的温/湿度通风阈值 + 自动/常开/常关三态手动覆盖。阈值可调正是这个功能能被演示的关键（把阈值调到当前读数以下，风扇立刻转，不必等环境真的变热）。风扇模式以**普通字符串**跨越边界（`"AUTO"`/`"MANUAL_ON"`/`"MANUAL_OFF"`），因此本控件仍然不 import `service`，符合 widgets 层的依赖约束。数值输入框设了 `setKeyboardTracking(False)`，输入"25"只在编辑结束时发一次信号而非每敲一键发一次；`set_settings()` 回填时屏蔽信号，避免"从平台读回的状态"被误当成"用户改动"再回写一遍
  - `metric_card.py`：`MetricCardWidget` —— 单通道关键指标卡片：当前值+单位+趋势箭头（纯展示计算，方向不代表好坏）+ 阈值状态边框
  - `status_banner.py`：`StatusBannerWidget` —— 正常/警告/报警三态状态横幅
  - `device_list_item.py`：`DeviceListItemWidget` —— 通过 `QListWidget.setItemWidget()` 叠加渲染的设备卡片（底层选择行为不变）
  - `device_panel.py`：`DevicePanelWidget` —— 设备 ID / 连接状态 / 控制占用状态 / 能力信息（当前 `ApiInterface` 未提供能力字段时显示面向最终用户的"未获取"，而非暴露内部类型名的调试文字）
  - `data_panel.py`：`DataPanelWidget` —— 多通道实时数据表（设备/通道/当前值/单位/状态五列，按 device_id+channel 分行、原地更新）+ 有上限的历史记录表格（可清空）；`realtime_group()`/`history_group()` 供 `MainWindow` 分别放入不同布局层级
  - `statistics_panel.py`：`StatisticsPanelWidget` —— 每 (device_id, channel) 一张统计信息卡片（当前值/最小/最大/平均/样本数），套在 `QScrollArea` 中
  - `control_panel.py`：`ControlPanelWidget` —— 订阅/暂停接收/获取控制权/释放控制权/发送命令 操作 + 活动日志（命令执行结果、控制权获取结果、报警红字记录、错误信息）

**已验证**：`ui/` 在 Simulator 模式与 Hardware 模式下**零代码差异**——`scripts/run_gui.py` 新增 `--mode hardware` 支持后（见 `docs/05_Test/Runtime_Mode.md`），`SerialChannel`/`RemoteDevice`/`HardwareDeviceReceiver`/`HardwareRuntimeRunner`/`QTimer` 全部只出现在该启动脚本里，`ui/` 目录下没有任何一处 import 它们（已用 grep 反复核实），四轮界面迭代均未改变这一点。

尚未实现（不在本次范围内）：

- QThread 后台线程（Iron Law 2；全程同步执行，暂无耗时操作需要移出主线程）
- Android 客户端（架构设计见 `docs/02_Architecture/Multi_Client_System_Architecture.md`，`ui/` 目录本身无任何代码）
- 真实传感器/真实设备数据源（`ChartWidget.add_point` 已预留通用接口；Hardware 模式的数据接收链路已在 `application/` 层实现，`ui/` 侧接入方式与 Simulator 模式完全相同，无需额外适配；但从未接过真实物理 MCU）
- 历史数据导出（CSV 等）——已识别为候选功能，尚未定案

## 设计约束

- 遵循 `docs/04_Development/Development_Rules.md`："禁止 UI 和通信逻辑混合"
- **只能调用 `src/api`**：不直接 import `device`、`communication`、`protocol`、`application`；`controller.py` 之外的文件（`main_window.py`、`widgets/*`）也不直接 import `api`，只经由 `controller.py`
- **Widget 独立**：`widgets/` 下所有组件均不 import `ui.controller`，只暴露 setter 方法与 Qt 信号，可脱离本项目的 Controller/Api 独立复用或测试
- 遵循 `.claude/skills/pyqt6-ui-development-rules`：MVC 分层、Signal/Slot 通信、布局管理器而非绝对像素坐标

## 依赖关系

`controller.py` 依赖 `core`、`api`、`service`（仅复用 `Command`/`DataPoint` 等共享概念模型类型，不调用 `service` 的具体实现）。`main_window.py` 依赖 `ui.controller` 与 `ui.widgets`。`widgets/*` 依赖 `PyQt6`、标准库，以及同层的 `ui.theme`/`ui.channel_display`（仅取用颜色常量、`set_class`/`set_state` 辅助函数、channel 展示文本，不依赖 `theme.py` 的 QSS/QPalette 装配逻辑）——这是 `ui/` 内部的同层依赖，不构成跨层调用。不被任何其他 `src/` 模块依赖。

## 相关文档

- `docs/02_Architecture/System_Architecture.md`
- `docs/02_Architecture/Multi_Client_System_Architecture.md`
- `.claude/skills/pyqt6-ui-development-rules/SKILL.md`

## `widgets/assistant_panel.py`（2026-09-08 新增）

环境问答聊天面板。与本包其它控件一样是 Passive View：不持有 `MainController`/`ApiInterface`，不 import `service`——答案来源以**普通字符串**跨过这条边界，和 `ventilation_panel.py` 传风扇模式的做法一致。

两个值得记的行为：

- **每条答案都标注是谁写的措辞**（「系统」/「模型改写」）。这不是装饰：平台的保证是"数字永远来自实测、只有措辞可能由模型改写"，把这一点画在界面上，等于把保证摆出来给人看，而不是留在设计文档里。
- **迟到的改写替换而不是追加**。模型改写要几秒才回来，追加一条会读成助手把同一件事说了两遍；替换则读成这条答案变好了。

界面位置：第 1 页底部行第二列（2026-09-18 起为 `[活动日志 2 | 环境问答 3 | 通风+调试 2]`，此前是 `[报警+历史 3 | 活动日志 2 | 环境问答 3 | 通风+调试 2]`，历史表移到第 2 页后腾出的宽度按原比例分掉，问答由 3/10 变为 3/7）。该行竖向 stretch 于 2026-09-08 由 2 提到 3——否则只够显示两三条消息。
