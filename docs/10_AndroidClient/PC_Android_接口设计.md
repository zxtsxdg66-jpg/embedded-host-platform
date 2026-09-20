# PC ↔ Android 局域网接口设计（REST + WebSocket）

> **文档定位**：本文档是 `docs/02_Architecture/Multi_Client_System_Architecture.md` 第 2.3 节"PC 内置网关"模式的具体接口设计，回答"REST 端点长什么样、WebSocket 消息格式是什么"这类实现层面的问题。
>
> **实现状态（2026-08-15 更新）**：本文档设计的接口**已经实现并实测通过**，实现位于
> `src/gateway/`（PC 端）+ `scripts/run_api_server.py`（启动入口）+ `android/`（Android 客户端）。
> 与本文档原始设计的差异、以及哪些仍未实现，见文末新增的"实现状态对照"一节——
> 其中"历史数据查询"仍然**未实现**，原因不变（PC 端 service/api 层没有该能力）。
>
> **接口设计原则**：本设计是现有 `src/api/interface.py`（`ApiInterface`）的**网络化封装**，不重新发明一套数据模型——REST/WebSocket 暴露的每一个字段，都能追溯到 `ApiInterface` 已有方法或 `service` 层已有数据类（`DataPoint`/`Command`/`CommandResult`/`ThresholdStatus`/`ChannelStatistics`/`DeviceStatusView`），不凭空设计 Android 端"应该"要什么字段。

---

## 一、总体架构

```
Android 客户端
    │  HTTP (REST)              │  WebSocket
    ▼                            ▼
┌─────────────────────────────────────────┐
│   PC 端新增：本地网络接口层（未实现）        │
│   职责：把 HTTP/WebSocket 请求翻译成对     │
│   ApiInterface 的调用，把 ApiInterface     │
│   的回调结果翻译成 HTTP 响应/WebSocket 消息 │
└─────────────────────────────────────────┘
                    │  纯本地方法调用（进程内，无网络）
                    ▼
        api.ApiInterface（已实现，local_api.LocalApi）
                    │
                    ▼
        application.ApplicationRuntime（已实现）
```

**架构边界**：新增的"本地网络接口层"是一个**新的适配器**，职责与 `ui/controller.py` 的 `MainController` 类似——都是"把 `ApiInterface` 的能力转换成另一种技术形式暴露出去"（`MainController` 转成 Qt 信号给 PyQt6 界面用，网络接口层转成 HTTP/WebSocket 给 Android 用），两者是**平级的两个 `ApiInterface` 消费方**，不是新的架构层，不改变 `System_Architecture.md` 定义的五层结构，也不改变 `api` 对下只依赖 `application`/`service`/`core` 的既有边界（网络接口层依赖 `api`，不会让 `api` 反过来依赖网络接口层）。放在 `src/` 的哪个位置由后续实施阶段决定（候选：新建 `src/gateway/` 包，或作为 `scripts/` 下的独立启动脚本+一个新模块，具体取决于是否需要在 `scripts/run_gui.py` 里同进程启动——本文档不预先决定，留待实现阶段）。

---

## 二、REST 端点设计

> 以下均为设计草案，实际路径前缀、版本号（如 `/api/v1/`）留待实现时确定。

### 2.1 GET /devices —— 获取设备列表

对应 `ApiInterface.list_devices()`。

**响应示例**：
```json
{
  "devices": ["mcu-1"]
}
```

### 2.2 GET /devices/{device_id}/status —— 获取设备状态

对应 `ApiInterface.get_device_status(device_id)`，字段取自 `application.runtime.DeviceStatusView`（`device_id`/`is_connected`/`is_occupied`/`occupant`，均已在现有代码中定义，未新增字段）。

**响应示例**：
```json
{
  "device_id": "mcu-1",
  "is_connected": true,
  "is_occupied": false,
  "occupant": null
}
```

### 2.3 GET /devices/{device_id}/channels/{channel}/history —— 查询历史数据

> **✅ 2026-09-17 起确定实现**：历史记录已与导师商定为毕设必须交付的功能，且手机端要能看历史，
> 见 `docs/02_Architecture/History_And_Cloud_Design.md` 第 0 节。**以下是当初的评估，保留以存档时间线**：
> 已实际检查过 `src/api/`、`src/service/`、`src/application/` 全部代码，**历史数据目前只存在于 `src/ui/widgets/data_panel.py` 的 `DataPanelWidget._history_list`（PyQt6 界面内部的表格控件状态）**，`service`/`application`/`api` 三层完全没有保存或暴露历史数据的能力——这是 UI 层自己维护的本地展示状态，Android 端作为独立进程无法访问。
>
> 要支持这个端点，需要先在 `service`（很可能是 `DataService` 或新增一个"历史缓冲"组件）与 `api.ApiInterface` 补一个类似 `get_history(device_id, channel, limit)` 的新能力，**这属于修改受保护的 `api`/`service` 接口，需要单独提出、说明原因并获得明确授权后才能实施**（对应 `docs/05_Test/Project_Status_Context.md` 第 7 节"开发约束"、`CLAUDE.md`"修改规则"）。本文档当初把这个端点记为**设计草案**。**2026-09-17 起该契约即为实现依据**，字段不变——
当初设计得足够克制，因而不必重新设计，Android 端与网关照此实现即可：

**响应示例（2026-09-17 已实现，以下即实际返回）**：
```json
{
  "device_id": "mcu-1",
  "channel": "temperature",
  "unit": "°C",
  "points": [
    {"value": 23.5, "timestamp": "2026-08-14T10:00:00+00:00", "valid": true}
  ]
}
```

两处与草案的差别，都是实现时才定的，记在这里以免 Android 端照草案写解析器：

- **`unit` 在顶层，不在每个点里。** 它是通道的属性、不是读数的属性，逐点重复 500 遍
  不多说明任何事。来源与实时推送一致（`gateway/channel_units.py`，见 7.3 节），
  所以同一个通道在 WebSocket 与本端点里拿到的单位必然相同。
- **`timestamp` 是带时区的 ISO-8601（`+00:00`）**，不是草案里的 `Z` 写法。
  存储层一律存 UTC（见 `History_And_Cloud_Design.md` 4.1 节），这里原样渲染，
  与 WebSocket 的 `data` 消息共用同一个渲染函数 `gateway.events.isoformat_or_none`，
  两端不会漂。

**查询参数**：`start`、`end`（ISO-8601，可省略）、`limit`（默认 500）。
时间戳格式错误返回 **400** 而不是退化成全量查询——"我要最近一小时、拿回了全部"
是客户端察觉不到的错答案。未知设备或通道不是错误，返回空 `points` 列表。

### 2.4 POST /devices/{device_id}/control/acquire —— 获取控制权

对应 `ApiInterface.acquire_control(device_id, client_id)`。`client_id` 建议由 Android 端生成一个稳定的客户端标识（如安装 ID），随请求体传入。

**响应示例**：
```json
{"acquired": true}
```

### 2.5 POST /devices/{device_id}/control/release —— 释放控制权

对应 `ApiInterface.release_control(device_id, client_id)`。

### 2.6 POST /devices/{device_id}/commands —— 提交控制指令

对应 `ApiInterface.submit_command(command)`，`Command` 字段（`device_id`/`command_type`/`origin`/`parameters`）均取自 `service.command_models.Command`。

**请求示例**：
```json
{"command_type": "PING", "parameters": {}}
```

**响应示例**（字段取自 `CommandResult`）：
```json
{
  "command_id": "b3f1...",
  "status": "SUCCESS",
  "message": "",
  "completed_at": "2026-08-14T10:00:05Z"
}
```

### 2.7 GET /devices/{device_id}/commands/{command_id} —— 查询指令结果

对应 `ApiInterface.get_command_result(command_id)`，响应结构同 2.6。

### 2.8 POST /assistant/ask —— 环境问答（2026-09-08 新增）

对应 `ApiInterface.ask(question)`。请求体 `{"question": "现在温度多少"}`，
响应 `{"text": "温度现在是 20.8℃，处于正常范围。", "source": "template"}`。

`source` 取自 `AnswerSource`，四种取值告诉客户端这句话由谁组织：

| source | 含义 |
| --- | --- |
| `template` | 规则识别 + 模板成句，全程无模型参与 |
| `model_intent` | 规则没认出问句，模型判断了它属于哪一类；句子与数字仍由程序生成 |
| `model` | 模型改写了措辞；数字仍来自程序，且经过接地校验 |
| `fallback` | 没能理解，返回"我会答什么"的清单 |

**这个端点不等待模型**。`ask()` 是同步的，返回的是毫秒级就绪的规则与模板答案；
模型若产出更好的措辞、或读懂了规则没认出的问句，那条答案会在数秒后经 WebSocket 补送（见 3.5）。
只调 REST 的客户端仍能拿到正确答案，只是看不到改进后的那条。

空问题返回 400 而不是帮助文案——后者是对"你能做什么"的正确回答，对一个什么都没带的请求则是误导。

---

## 三、WebSocket 消息设计

单一 WebSocket 连接（如 `ws://<PC局域网IP>:<端口>/ws`），服务端按事件类型推送不同消息，客户端用 `type` 字段区分。

### 3.1 实时数据推送

对应 `ApiInterface.subscribe_data(device_id, channel_id, callback)` 的回调数据，`DataPoint` 字段（`device_id`/`channel`/`value`/`timestamp`/`valid`）取自 `service.data_models.DataPoint`。

```json
{
  "type": "data",
  "device_id": "mcu-1",
  "channel": "temperature",
  "value": 23.5,
  "timestamp": "2026-08-14T10:00:00Z",
  "valid": true
}
```

> **注意**：`DataPoint` 本身没有 `unit`（单位）字段——PC 端 UI 的"单位"文字是 `ui/channel_display.py` 里维护的**展示层映射**（`channel_unit()`），不是数据模型的一部分。若 Android 端要显示"℃"/"%"/"dB"这类单位，两个可行方案：①Android 端自己按 `channel` 名称维护一份同样的映射（简单，但存在与 PC 端 `channel_display.py` 定义"漂移"的风险）；②本网络接口层在推送时补一个 `unit` 字段（服务端从 `channel_display.py` 读取后一并发出）。**本文档暂不替你决定，留到实现阶段选择**，倾向于方案②以保持"单位映射只有一处权威定义"的原则（呼应 `channel_display.py` 自己的设计初衷）。

### 3.2 阈值报警状态推送

对应 `ApiInterface.subscribe_alarm_status(callback)` 的回调数据，字段取自 `service.sensor_data_processor.ThresholdStatus`（`device_id`/`channel`/`value`/`threshold`/`kind`/`triggered`）。

```json
{
  "type": "alarm_status",
  "device_id": "mcu-1",
  "channel": "noise",
  "value": 85.2,
  "threshold": 80.0,
  "kind": "ABOVE_MAX",
  "triggered": true
}
```

### 3.3 统计信息推送

对应 `ApiInterface.subscribe_statistics(callback)` 的回调数据，字段取自 `service.sensor_data_processor.ChannelStatistics`（`current`/`minimum`/`maximum`/`average`/`sample_count`）。

```json
{
  "type": "statistics",
  "device_id": "mcu-1",
  "channel": "temperature",
  "current": 23.5,
  "minimum": 20.1,
  "maximum": 25.3,
  "average": 22.7,
  "sample_count": 128
}
```

### 3.5 问答答案补送（2026-09-08 新增）

```json
{"type": "assistant", "text": "温度现在是 23.6℃，处于正常范围。", "source": "model_intent"}
```

字段与 2.8 的 REST 响应同名同义。它出现的时机只有一个：某次 `POST /assistant/ask` 之后，
模型给出了可用结果。指令类语句（"把风扇打开"）不会有补送——确认语不交给模型改写，
每次都该一模一样。

客户端的处理方式：把它替换掉刚才那条 REST 答案，而不是追加一条新气泡。

### 3.4 设备状态变化推送（设计草案）

> **⚠️ 同样需要新增能力**：当前 `ApiInterface` 没有"设备状态变化订阅"这个能力——`get_device_status()` 是一次性查询，不是订阅式推送。PC 端 UI 目前是通过其它信号间接得知设备状态变化的（不在 `ApiInterface` 范畴内）。若 Android 端需要"设备离线/占用状态实时刷新"而不是每次轮询查询，需要新增一个类似 `subscribe_device_status(callback)` 的能力，**同样属于修改受保护 `api` 接口，需要单独授权**。本文档先记录设计意图，不代表已确认要做。

---

## 四、Android 端能力与 PC 端能力对照表

| Android 端需求（用户原话） | 对应 PC 端能力 | 现状 |
| --- | --- | --- |
| 获取设备列表 | `ApiInterface.list_devices()` | ✅ 已实现，REST 端点 2.1 直接可用 |
| 获取实时数据 | `ApiInterface.subscribe_data()` | ✅ 已实现，WebSocket 3.1 直接可用 |
| 显示多通道数据（温湿噪） | 同上，按 `channel` 区分 | ✅ 已实现 |
| 显示设备状态 | `ApiInterface.get_device_status()` | ✅ 已实现，REST 端点 2.2 直接可用；若要"实时刷新"而非轮询，需要 3.4 的新能力 |
| 显示报警信息 | `ApiInterface.subscribe_alarm_status()` | ✅ 已实现，WebSocket 3.2 直接可用 |
| 查看历史数据 | `ApiInterface.query_history()` | 🔨 **2026-09-17 起实现中**：已获授权，见 2.3 节契约与 `History_And_Cloud_Design.md`；手机端历史页为该文档分期表的 P1b |
| 发送控制指令（可选） | `ApiInterface.submit_command()` 等 | ✅ 已实现，REST 端点 2.4/2.5/2.6/2.7 直接可用 |
| 环境问答（2026-09-08 追加） | `ApiInterface.ask()` | ✅ 网关侧（2.8 + 3.5）与 Android 问答页均已实现，**2026-09-09 真机验证通过** |

**结论**：用户列出的 7 项 Android 能力中，**6 项已经有现成的 PC 端能力可以直接封装**，只有"查看历史数据"这一项需要先给 `service`/`api` 层新增能力。建议实现顺序上，先做不需要改动受保护接口的 6 项，历史数据查看放到后面单独提出、评估、授权后再做——这样可以让 Android 端尽早跑起来一个可用版本，不被"历史数据"这一项卡住整体进度。

> **2026-09-17 更新**：上述顺序已按原计划走完，6 项均已实现并真机验证。第 7 项"查看历史数据"
> 现已与导师商定为毕设交付功能，开始实施——`api`/`service` 的扩展已获授权，2.3 节契约不变。
> 当初"不被历史数据卡住整体进度"的判断事后看是对的：移动端因此早就跑通了，现在只需在
> 既有结构上加一个页面与一个查询方法，`GatewayWebSocket` 与 `MessageParser` 完全不用动。

---

## 五、技术选型建议（未决定，需要你确认后才安装任何依赖）

- **PC 端 REST + WebSocket 服务**：Python 生态里 FastAPI（内置 WebSocket 支持、原生 async）或 Flask+Flask-SocketIO 是常见选择；具体选哪个、要不要引入，**属于新增第三方依赖，按项目规则需要你明确授权后才能安装**（`CLAUDE.md`"禁止事项"："禁止自动安装依赖包，除非用户在当次任务中明确授权"），本文档只列出候选，不代表已选定
- **Android 端网络库**：Retrofit（REST）+ OkHttp（WebSocket）是 Android 生态的常见组合，具体技术栈留待 Android 项目实际搭建时确定

---

## 六、当前进度与下一步

- [x] 架构模式确定：PC 内置网关（`Multi_Client_System_Architecture.md` 第 2.3 节）
- [x] REST 端点设计（本文档第二节）
- [x] WebSocket 消息设计（本文档第三节）
- [x] 识别出"历史数据查询"是唯一需要新增 PC 端能力的项目
- [ ] 你确认本设计（尤其是第三节 3.1 节"unit 字段放哪一端"的取舍、第五节技术选型）
- [ ] 你确认是否现在就着手"历史数据"能力的 `service`/`api` 扩展，还是先跳过、做完其余 6 项能力再说
- [ ] PC 端网络接口层实现（未开始）
- [ ] Android 项目搭建（未开始）

---

---

## 七、实现状态对照（2026-08-15）

### 7.1 已实现且实测通过

| 本文档设计 | 实现位置 | 验证方式 |
| --- | --- | --- |
| GET /devices | `gateway/server.py` | 实跑服务 + 自动化测试 |
| GET /devices/{id}/status | 同上 | 同上 |
| POST …/control/acquire、/release | 同上 | 同上 |
| POST …/commands、GET …/commands/{id} | 同上 | 同上 |
| WS `data` 消息 | `gateway/events.py` | 实连 WebSocket 收到 |
| WS `alarm_status` 消息 | 同上 | 同上 |
| WS `statistics` 消息 | 同上 | 同上 |
| Android 端消费以上接口 | `android/` | APK 构建成功 + 10 个 JVM 单元测试（含 3 条用真实抓包报文） |

### 7.2 实现时新增（本文档原设计中没有的）

- **GET /health**：返回 `status`/`mode`/`websocket_subscribers`/`published_count`/`dropped_count`。
  加它的原因是排障需要——`mode` 让客户端能判断"当前数据是模拟还是真实硬件"（并据此
  在 Android 界面上显示模拟数据警告），计数器让"到底有没有在推数据"变成可观测的，
  而不是只能靠盯界面猜。

### 7.3 3.1 节遗留问题的实际处理：`unit` 字段

本文档 3.1 节曾把"unit 放服务端还是放 Android"列为待定，倾向服务端。**实现时选择了
服务端附加**，但过程中发现一个当时没预料到的约束：

`ui/channel_display.py` 虽然是纯数据映射，但 `import ui.channel_display` 会执行
`ui/__init__.py`，从而**连带 import PyQt6**（已实测：会拉进 5 个 PyQt6 模块）。
网关是无界面服务，不应因为三条单位映射而依赖 GUI 框架；且 `gateway` 与 `ui` 是
架构上的平级模块，互相 import 也不合适。

因此实现为：`gateway/channel_units.py` 保存一份**独立的**映射副本，并在文件头明确
记录这是有意的重复、以及为什么不能直接 import。

> **这是一个仍需你拍板的遗留问题**：现在 `温度=°C` 这类映射在代码库里有两份
> （`ui/channel_display.py` 与 `gateway/channel_units.py`），存在漂移风险，而这
> 恰恰是当初创建 `channel_display.py` 想避免的。干净的解法是把映射提取到一个
> 不依赖 PyQt6 的共享模块，两边都 import 它——但那需要改动已有文件，未擅自执行。

### 7.4 仍未实现

- **历史数据查询（2.3 节）**：~~未实现~~ → **2026-09-17 起实现中**（已定为毕设交付功能，手机端也要看）。
  以下为当初未实现的原因，保留存档：PC 端历史数据目前只存在于
  `ui/widgets/data_panel.py` 的 QTableWidget 内部，`service`/`application`/`api`
  三层都没有该能力。实现它需要扩展受保护的 `api`/`service` 接口，需单独授权。
  已在 `tests/gateway/test_server.py` 里写了一条测试**断言该端点返回 404**，
  把"当前故意没有它"这个决定固定下来，避免以后有人误以为漏做了。
- **设备状态变化推送（3.4 节）**：未实现，`ApiInterface` 目前只有一次性查询
  `get_device_status()`，没有订阅式能力。Android 端当前是连接时拉取一次。

---

*（本文档最初为设计阶段产出；2026-08-15 起同步了实际实现状态。）*
