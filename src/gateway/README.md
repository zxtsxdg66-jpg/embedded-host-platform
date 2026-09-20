# gateway

## 职责

`gateway` 是 PC 端内置的**局域网网络接口层**（REST + WebSocket），把 `api.ApiInterface` 已有的能力重新表达为 HTTP 响应与 WebSocket 消息，供 Android 客户端消费。

对应 `docs/02_Architecture/Multi_Client_System_Architecture.md` 第 2.3 节确定的接入模式——**网关模式的特化形式：PC 上位机进程自己兼任网关**，不引入独立的第三方网关进程；接口细节见 `docs/10_AndroidClient/PC_Android_接口设计.md`。

**它不是新增的架构层**，而是与 `ui/` **平级**的第二个 `api.ApiInterface` 消费方：

```
                     ┌──► ui/       （转成 Qt 信号，给 PyQt6 界面）
api.ApiInterface ────┤
                     └──► gateway/  （转成 HTTP 响应 / WebSocket 消息，给 Android）
```

已实现（第一阶段，2026-08-15）：

- `server.py`：`create_app(api, subscriptions, mode_label)` —— FastAPI 应用工厂，**9 个 REST 端点 + 1 个 WebSocket 端点**（2026-09-18 实测核对：`/health`、`/devices`、设备状态、获取/释放控制权、下发命令、命令结果、历史查询、环境问答），每一个都是对**已有** `ApiInterface` 方法的翻译，未新增任何业务逻辑

  | 方法 | 路径 | 对应 `ApiInterface` 方法 |
  | --- | --- | --- |
  | GET | `/health` | 无（存活探测 + 模式标签 + `EventHub` 计数器） |
  | GET | `/devices` | `list_devices` |
  | GET | `/devices/{device_id}/status` | `get_device_status` |
  | POST | `/devices/{device_id}/control/acquire` | `acquire_control` |
  | POST | `/devices/{device_id}/control/release` | `release_control` |
  | POST | `/devices/{device_id}/commands` | `submit_command` |
  | GET | `/devices/{device_id}/commands/{command_id}` | `get_command_result` |
  | POST | `/assistant/ask` | `ask`（2026-09-08 新增） |
  | WS | `/ws` | `subscribe_data` / `subscribe_alarm_status` / `subscribe_statistics`，外加问答答案补送 |

  错误映射：`DeviceNotFoundError` → 404；`CommandAuthorityError`（未获取控制权）与 `CommandDeliveryError`（设备未在超时内应答）→ 409。

- `event_hub.py`：`EventHub` —— 把**同步的** `ApiInterface` 回调桥接到 **asyncio** 的 WebSocket 发送。`publish()` 可从任意线程调用（数据管线线程），经 `loop.call_soon_threadsafe` 投递到事件循环后扇出。每个订阅者持有**独立的有界队列**（默认 100），客户端消费不及时时只丢弃**它自己的**最旧消息并计入 `dropped_count`，既不阻塞数据管线（该线程同时喂着 PyQt6 界面），也不无限增长；`published_count`/`dropped_count`/`subscriber_count` 经 `/health` 暴露，使丢弃可观测而非静默。
- `assistant_sink(app)`：给组合根用的 `(text, source)` 回调，把**迟到的**模型答案推给所有 WebSocket 客户端。
  形状与 `automation_wiring.make_poll_once` 的 `on_assistant_answer` 参数一致，因此启动脚本可以直接把它交进去；
  `run_all.py` 则用一个 lambda 同时喂给桌面控制器和手机。存在的理由是不让启动脚本去碰 `app.state.hub`——
  扇出由谁承载是本包自己的事。

  **问答为什么是"REST 立即答 + WebSocket 补送"而不是一个请求等到底**：`ApiInterface.ask()` 同步返回
  规则与模板答案（毫秒级），而模型改写或分类要数秒。把请求挂住等模型，会让没接模型的部署也慢下来，
  且手机端一旦超时就什么都拿不到；分成两段之后，只调 REST 的客户端仍然拿到正确答案，
  接了模型的客户端多收一条替换消息。

- `events.py`：四种 WebSocket 消息（`data` / `alarm_status` / `statistics` / `assistant`）的序列化，字段全部取自 `DataPoint` / `ThresholdStatus` / `ChannelStatistics`，未发明字段；唯一由服务端附加的是 `unit`（`DataPoint` 本身没有单位字段，且未为此给它加字段）。
- `channel_units.py`：channel → 展示单位映射。**这是 `ui/channel_display.py` 的一份有意为之的重复**，理由见下方"已知遗留问题"。

订阅关系由**调用方装配**而非本包自行发现：`create_app()` 的 `subscriptions` 参数（`(device_id, channel_id)` 列表）由组合根 `scripts/run_api_server.py` 传入——"有哪些通道"是组合决策，与 `SimulatorRuntimeRunner` 的 targets 同理。

启动入口：`scripts/run_api_server.py`（`run_api_server_手机网关.bat` 为交互式包装，会打印手机要填的局域网 IP）；与 PC 界面同进程同跑用 `scripts/run_all.py`（`run_all_界面加网关.bat`），硬件模式下两端共用一条串口。

尚未实现（有意为之，不在本包范围内）：

- **历史数据端点**：`service`/`application`/`api` 三层均无历史数据能力（历史记录只存在于 `ui/widgets/data_panel.py` 的表格控件内部）。本包**不绕过架构去读取界面控件状态**；补齐它需要扩展受保护的 `api`/`service` 接口，需单独授权。`tests/gateway/test_server.py` 中有一条测试断言该端点返回 404，把"故意没做"这个决定固定下来，避免后人误判为漏做。
- 设备状态变化的主动推送（当前设备状态只能经 REST 轮询获取）
- 鉴权与传输加密（见下方"设计约束"）

## 设计约束

- **只作为 `api.ApiInterface` 的网络表达**：不实现任何设备/通信/协议逻辑，不新增业务概念；每个端点都应能一一对应到某个已有的 `ApiInterface` 方法。
- **不 import `ui`，也不被 `ui` import**：两者是架构对等物，互相 import 属于呈现层之间的横向依赖。
- **必须能在没有 GUI 工具链的环境下运行**：本包是无界面服务，不得依赖 PyQt6。
- **回调绝不把异常抛回数据管线**：`EventHub.publish()` 从数据发布线程被同步调用，该线程同时驱动着 PyQt6 界面的数据链路，因此 `publish()` 承诺永不抛出（事件循环已关闭等情况静默返回）。
- **背压只影响慢客户端自己**：宁可丢弃单个客户端的最旧消息，也不阻塞发布方、不让队列无限增长。
- **CORS 当前为宽松放行**：仅因为客户端只在用户自己的局域网内（手机 + PC 同一 Wi-Fi/热点）、本阶段无鉴权也无敏感数据。**超出可信网络暴露本服务前必须重新评估**，见 `docs/10_AndroidClient/第一阶段测试流程.md`。

### 已知遗留问题：单位映射重复两份

`channel_units.py` 的 `CHANNEL_UNITS` 与 `ui/channel_display.py` 的同名映射是**同一份内容的两个副本**（`temperature`→`°C`、`humidity`→`%`、`noise`→`dB`）。原因记录在 `channel_units.py` 文件头：`import ui.channel_display` 会执行 `ui/__init__.py`，从而连带 import PyQt6（2026-08-14 实测拉进 5 个模块），无界面网关不应依赖 GUI 框架；且 `gateway` 与 `ui` 是架构平级模块。

干净的解法是把映射提取到一个无依赖的共享模块供两边 import，但这要改动已有文件，**未擅自执行**；用户已明确表示"先放着，等以后加第四个传感器时再处理"。在那之前**新增或修改通道单位时必须手工同步这两处**。

## 依赖关系

依赖 `api`（唯一的功能委托对象）、`core`/`service`（仅复用 `Command`/`DataPoint`/`ThresholdStatus`/`ChannelStatistics` 等经由 `api` 签名暴露的共享概念模型类型）、以及第三方的 `fastapi`/`uvicorn[standard]`/`pydantic`。

**不依赖** `device`、`communication`、`protocol`——Android 客户端不应知道 COM 口、波特率、CRC、帧格式的存在，本层同样不应知道。**不依赖 `ui`**，也不被 `src/` 下任何其他模块依赖（仅由 `scripts/run_api_server.py`、`scripts/run_all.py` 两个组合脚本装配）。

新增运行时依赖 `fastapi`、`uvicorn[standard]` 与测试依赖 `httpx` 已写入 `pyproject.toml`（均由用户显式授权后安装）。

## 测试

`tests/gateway/` 共 **17 个用例**（`test_server.py` 11、`test_events.py` 6），全部通过。`test_server.py` 用 FastAPI 的 `TestClient` 在进程内跑**真实的 ASGI 应用**（真实路由、真实序列化、真实 WebSocket 握手），对接的是按 `scripts/run_api_server.py` 完全相同方式装配出的真实 `ApplicationRuntime` + `LocalApi`，API 层无任何 mock。

真机端到端联调已通过（2026-08-15 simulator 模式、2026-08-16 硬件模式），见 `docs/05_Test/Project_Status_Context.md` 5.2 / 5.4 / 5.5 节。

## 相关文档

- `docs/02_Architecture/Multi_Client_System_Architecture.md`（第 2.3 节：接入模式确定；第 4 节：分层关系）
- `docs/02_Architecture/Software_Structure.md`（"实际落地结构"一节）
- `docs/02_Architecture/Core_Service_Design.md`（第 5.2 节网关模式调用关系、第 8 节 API 扩展方向）
- `docs/10_AndroidClient/PC_Android_接口设计.md`（REST 端点与 WebSocket 消息格式的完整定义）
- `docs/10_AndroidClient/第一阶段测试流程.md`（联调步骤与防火墙/AP 隔离/代理三类问题排查）
- `docs/04_Development/项目代码结构导览.md`（第 1.9 节：本包的逐文件讲解）
