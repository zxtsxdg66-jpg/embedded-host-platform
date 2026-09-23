# Android 客户端与网关接口

## 客户端

手机不直连设备，不知道串口、波特率、CRC 与帧格式。所有数据来自 PC 网关的 REST 与 WebSocket，
和桌面端看到的是同一份。为什么这样分工见 [`decisions/07-gateway.md`](decisions/07-gateway.md)。

| 页面 | 内容 |
| --- | --- |
| 首页 | 三张指标卡（当前值、最小/最大/平均、越限状态）、本次连接以来的折线、连接状态、设备与日志 |
| 环境问答 | 问句走 REST 立即得到模板答案；PC 接了本地模型时，改写版稍后经 WebSocket 补送并替换原气泡 |
| 历史 | 查 PC 的本地历史库，一次一条通道，最多 200 条；不开 WebSocket（历史不会自己变） |
| 设置 | PC 地址，持久化保存 |

### 技术选择

| 项 | 选择 | 原因 |
| --- | --- | --- |
| 语言 | Kotlin | — |
| 界面 | XML 布局 + ViewBinding | 不用 Compose：要额外对齐编译器与 BOM 版本，而 Material Components 已经够用 |
| 网络 | OkHttp | 一个库覆盖 REST 与 WebSocket，不再引入 Retrofit |
| JSON | Android 内置的 `org.json` | 接口只有几个字段，不引入 Gson/Moshi |
| 列表 | `ScrollView` + `LinearLayout` | 不引入 RecyclerView；作为代价，历史查询上限压到 200 条 |

依赖刻意保持最少：每加一个依赖就多一次下载与版本解析，离线环境下拿不到未缓存的新依赖。

### 结构

```
android/app/src/main/java/com/example/envmonitor/
├── MainActivity.kt / AssistantActivity.kt / HistoryActivity.kt / SettingsActivity.kt
├── ServerConfig.kt              PC 地址（不硬编码 localhost）
├── ui/                          纯展示：指标卡、自绘折线、连接状态、按通道的小数位
└── data/                        网络与解析，不依赖 Android 视图
    ├── GatewayClient.kt         REST
    ├── GatewayWebSocket.kt      WebSocket，断线指数退避重连（1 s 起，上限 32 s）
    ├── MessageParser.kt         WebSocket 消息解析；不认识的类型返回"未知"并忽略
    ├── HistoryParser.kt         历史响应解析
    ├── StallDetector.kt         连接假死判定：TCP 没断、但 10 秒没有任何数据
    └── Models.kt                字段与 PC 端的类型一一对应，不自行发明
```

解析与判定都写成不依赖 Android 的纯 Kotlin，这样可以在 JVM 上做单元测试，不需要模拟器。

**连接状态有六种**，其中一种是"已连接，暂无数据"：WebSocket 没断，但服务端已经不推了。
只看 TCP 连接是否存活的话，这种假死会显示成"已连接"，而界面上的数字其实早就不动了。

### 构建与测试

```bash
cd android
./gradlew assembleDebug          # Windows: gradlew.bat assembleDebug
./gradlew testDebugUnitTest      # JVM 单元测试 41 项
```

工程自带 Gradle Wrapper，也可以直接用 Android Studio 打开 `android/`。

**已知限制：路径里有非 ASCII 字符时，JVM 单元测试会失败**（`ClassNotFoundException`）。
Kotlin 编译是成功的，是测试进程的 classpath 加载不到。把工程复制到纯英文路径下再跑即可。打包 APK 不受影响。

### 运行

1. PC 上启动网关：`python scripts/run_api_server.py`（或双击 `run_api_server_手机网关.bat`，它会打印本机局域网地址）
2. 手机与 PC 连同一个 Wi-Fi 或热点
3. App 里填 PC 的局域网 IP。**不要填 `localhost` 或 `127.0.0.1`**——在真机上那指向手机自己；模拟器用 `10.0.2.2`

连不上时依次排查：两端是否在同一网络、PC 防火墙是否放行 8000 端口、路由器是否开了 AP 隔离（客户端之间互相不可见）、
手机是否开着代理或 VPN。

网关用的是明文 `http://` 与 `ws://`（局域网内、无敏感数据、无鉴权），所以 App 的网络安全配置放开了明文流量。
暴露到可信网络之外之前，这一条必须重新设计。

## 网关接口

默认端口 8000。浏览器控制台（`web/`）用的是同一套接口。

### REST

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 存活探测；运行模式；WebSocket 订阅者数与已发布、已丢弃消息数 |
| GET | `/devices` | 设备 id 列表 |
| GET | `/devices/{id}/status` | 连接状态、是否被占用 |
| POST | `/devices/{id}/control/acquire` | 获取控制权 |
| POST | `/devices/{id}/control/release` | 释放控制权 |
| POST | `/devices/{id}/commands` | 下发命令（需先获取控制权） |
| GET | `/devices/{id}/commands/{command_id}` | 命令结果 |
| GET | `/devices/{id}/channels/{channel}/history` | 历史读数，新的在前；参数 `start`、`end`（ISO-8601）、`limit`（默认 500） |
| POST | `/assistant/ask` | `{"question": "..."}`，立即返回模板答案，另附意图、事实与改写追溯 |
| GET | `/ventilation` | 通风阈值、风扇模式、最近一次决策 |
| PUT | `/ventilation/thresholds` | `{"temperature_max": ..., "humidity_max": ...}` |
| PUT | `/ventilation/mode` | `{"mode": "AUTO" \| "MANUAL_ON" \| "MANUAL_OFF"}` |
| GET | `/link/statistics` | 串口链路计数；没有字节流的模式下 `active` 为 false |

错误映射：设备不存在 → 404；没有控制权、设备在超时内未应答 → 409；参数不合法（非有限数值、未知模式、时间格式错误）→ 400。
时间格式错误返回 400 而不是静默查全部——"我问的是最近一小时，拿回来的是全部数据"是那种客户端很难察觉的错误。

### WebSocket `/ws`

连接后服务端主动推送，每条消息都带 `type` 字段：

| `type` | 字段 | 何时推送 |
| --- | --- | --- |
| `data` | `device_id` `channel` `value` `unit` `timestamp` `valid` | 每条读数 |
| `statistics` | `device_id` `channel` `unit` `current` `minimum` `maximum` `average` `sample_count` | 每条读数之后 |
| `alarm_status` | `device_id` `channel` `value` `unit` `threshold` `kind`（`ABOVE_MAX` / `BELOW_MIN`） `triggered` | 每次阈值评估 |
| `fan_decision` | `should_run` `mode` `reason` | 通风控制器每次决策 |
| `assistant` | `text` `source` | 模型改写好之后补送 |
| `assistant_detail` | 同上，另加意图、事实与每次改写的判定 | 与 `assistant` 同时推送 |
| `link_event` | `kind` `timestamp` `raw`（空格分隔的大写十六进制） `length` `device_id` `command_type` `payload` `detail` | 每一帧、每一次链路异常 |

`reason` 是给人看的文字，客户端可以显示，不要解析。

**兼容规则：只增不改。** REST 只增字段，WebSocket 只增消息类型；客户端忽略不认识的字段与类型。
为浏览器控制台新增的三种消息（`fan_decision`、`assistant_detail`、`link_event`）没有让已发布的 App 做任何改动。

**慢客户端只影响自己。** 每个客户端一条容量 100 的队列，满了只丢这个客户端自己最旧的消息，
丢弃数经 `/health` 可见。
