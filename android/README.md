# Android 客户端（第二阶段：最终展示版 UI）

PC 上位机的**移动客户端**。不直接连接 STM32，不做 Modbus/I²C/传感器采集——
所有数据都来自 PC 网关（`scripts/run_api_server.py`）通过局域网提供的
REST + WebSocket 接口。架构依据见 `docs/02_Architecture/Multi_Client_System_Architecture.md`
第 2.3 节，接口定义见 `docs/10_AndroidClient/PC_Android_接口设计.md`。

## 技术栈

| 项 | 选择 | 原因 |
| --- | --- | --- |
| 语言 | Kotlin | Android 官方首选 |
| 界面 | XML 布局 + ViewBinding（不是 Compose） | 第一阶段只要最小测试界面；Compose 需要额外的编译器/BOM 版本对齐，在只做验证界面时是不必要的风险。第二阶段做最终 UI 时也**没有迁移 Compose**：Material Components 与 ConstraintLayout 早已在依赖里，够用 |
| 网络 | OkHttp（REST + WebSocket 都用它） | 一个库同时覆盖两种需求，不额外引入 Retrofit |
| JSON | `org.json`（Android 内置） | 接口只有几个字段，不引入 Gson/Moshi |

依赖刻意保持到最少——依赖越少，版本冲突的排查成本越低。

## 目录结构

```
android/
├── settings.gradle.kts / build.gradle.kts / gradle.properties
├── local.properties            SDK 路径（本机相关）
└── app/
    ├── build.gradle.kts
    └── src/
        ├── main/
        │   ├── AndroidManifest.xml
        │   ├── java/com/example/envmonitor/
        │   │   ├── MainActivity.kt          环境监测首页 + 连接流程
        │   │   ├── AssistantActivity.kt     环境问答页（2026-09-08；POST /assistant/ask，模型改写版经 WebSocket 补送后替换原气泡）
        │   │   ├── HistoryActivity.kt       历史读数页（2026-09-17；GET .../history，查 PC 本地历史库，不开 WebSocket）
        │   │   ├── SettingsActivity.kt      连接设置页（只保存地址，不碰 WebSocket）
        │   │   ├── ServerConfig.kt          PC 地址配置（持久化，不硬编码 localhost）
        │   │   ├── ui/                      纯展示层（不含任何网络逻辑）
        │   │   │   ├── MetricCardView.kt    温/湿/噪指标卡
        │   │   │   ├── SparklineView.kt     自绘折线（本次连接以来，非历史数据）
        │   │   │   ├── ConnectionUiState.kt 连接状态六态
        │   │   │   └── ChannelFormat.kt     按通道的小数位
        │   │   └── data/                    ← 第二阶段一行未改
        │   │       ├── Models.kt            数据模型（字段全部对应 PC 端真实类型）
        │   │       ├── MessageParser.kt     WebSocket 报文解析（纯 Kotlin，可 JVM 测试）
        │   │       ├── GatewayClient.kt     REST 客户端
        │   │       ├── GatewayWebSocket.kt  WebSocket + 自动重连
        │   │       ├── HistoryParser.kt       历史响应解析（2026-09-17；纯 org.json 对象，可 JVM 测试）
        │   │       ├── StallDetector.kt     WebSocket 假死判定（2026-09-09 从 MainActivity 抽出，纯函数、可 JVM 测试）
        │   └── res/                         布局、配色、字符串、图标、网络安全配置
        └── test/                            JVM 单元测试（不需要模拟器）
```

## 构建

工程自带 Gradle Wrapper（`gradlew` / `gradlew.bat`，Gradle 8.7），**不需要本机预先装 Gradle**：

```bash
cd android
./gradlew assembleDebug       # Windows: gradlew.bat assembleDebug
                              # 产物：app/build/outputs/apk/debug/app-debug.apk
```

或直接用 Android Studio 打开 `android/` 目录运行（它会自动识别 Wrapper 与
`local.properties` 里配置的 SDK 路径，不会重复下载一套 SDK）。

### ⚠️ 中文路径的已知限制（已实测）

> **2026-09-17 复验**：这条限制依然成立，本次开发历史页时又原样撞上一次——在 `D:\毕业设计ndroid` 下 `testDebugUnitTest` 四个测试类全部 `ClassNotFoundException`，连早已通过的 `MessageParserTest`、`StallDetectorTest` 也一样，而 `--rerun-tasks` 强制重编译无用；复制到纯 ASCII 路径后立即 **BUILD SUCCESSFUL，40 项全过**（`MessageParserTest` 13、`StallDetectorTest` 9、`HistoryParserTest` 11、`ChannelFormatTest` 7）。症状与 2026-08-15 记录的完全一致：Kotlin 编译成功、`.class` 确实生成了，是测试 worker 的 classpath 加载不到。

本工程位于 `D:\毕业设计\android`，路径含中文。实测结果：

- ✅ **打包 APK 可以正常成功**——`gradle.properties` 里已加 `android.overridePathCheck=true`
  绕过 AGP 的非 ASCII 路径拦截
- ❌ **JVM 单元测试在中文路径下会失败**（`ClassNotFoundException`，Kotlin 编译是成功的，
  是测试 worker 的 classpath 编码问题），需要复制到英文路径再跑：

```bash
robocopy D:\毕业设计\android D:\envmonitor-ascii-build /E /XD build .gradle
cd D:\envmonitor-ascii-build
gradle testDebugUnitTest
```

## 运行前提

1. PC 端先启动网关：`python scripts/run_api_server.py`
2. 手机与 PC 连同一个 Wi-Fi/热点
3. App 内填入 PC 的局域网 IP（`ipconfig` 查看），**不要填 localhost/127.0.0.1**
   （真机上那指向手机自己；模拟器请用 `10.0.2.2`）

完整测试步骤见 `docs/10_AndroidClient/第一阶段测试流程.md`。

## 阶段范围

**第一阶段（已真机验证）**：设备列表、设备状态、WebSocket 实时数据（温/湿/噪）、
报警消息接收、连接状态显示、断线自动重连（指数退避）、非法数据与未知消息类型的容错。

**第二阶段（UI/UX，2026-08-16）**：固定深色工业主题；首页重构为
「系统状态 → 三张指标卡 → 实时状态条 → 设备/日志」四层；连接状态收敛为六态
（含 WebSocket 假死时的"已连接，暂无数据"）；走动的相对更新时间与会话接收计数；
统计信息（最小/最大/平均/样本数）接入卡片；阈值超限的卡片级呈现；
连接设置独立成页。方案与实施记录见 `docs/10_AndroidClient/第二阶段_UI优化方案.md`。

**第二阶段之后的增补（2026-09-08～09，2026-09-14 补记于本文件）**：
- **环境问答页** `AssistantActivity.kt`，与 PC 端问答面板用同一套后端：问句走 `POST /assistant/ask`，立即拿到模板答案；PC 接了本地模型时，改写版稍后经 WebSocket 补送并**替换**原气泡。该页自己开一条 WebSocket，没有从 `MainActivity` 转发，是为了不改动第一阶段已经真机验证过的首页连接流程。`data/Models.kt`、`MessageParser.kt`、`GatewayClient.kt`、`GatewayWebSocket.kt` 为此相应扩展。接口见 `docs/10_AndroidClient/PC_Android_接口设计.md`
- **`StallDetector.kt`**：WebSocket 假死（TCP 没断、服务端已停推）的判定原先内联在 `MainActivity.onTick()`，抽成不依赖 Android 的纯函数，补了 JVM 单测（`StallDetectorTest.kt`），阈值 10 秒
- **历史读数页** `HistoryActivity.kt`（2026-09-17）：经 `GET /devices/{id}/channels/{channel}/history` 查 **PC 端本地历史库**——手机不直连云端、不持有任何云端凭证，也不在本机另存一份，两端看到的是同一份数据。该页**不开 WebSocket**（历史不会自己变，刷新即重查），一次只看一条通道。沿用问答页的做法用 `ScrollView` + `LinearLayout` 逐条加视图，**不引入 RecyclerView**，作为代价查询上限压到 200 条。解析抽成纯对象 `data/HistoryParser.kt`（照 `MessageParser` 的先例，否则 JVM 里测不了），时刻与数值的格式化归 `ui/ChannelFormat.kt`——它早就定了"按通道定小数位"的规矩（湿度不显示小数位，因为传感器精度只有 ±2%），我起初在页面里写死两位小数，是绕过了这条既有约定

> **验证状态（2026-08-16）**：第二阶段 UI 已通过真机验证，含断线自动重连；并已在
> **真实硬件模式**下验证——PC 侧用 `run_all_界面加网关.bat` 时，手机与 PC 界面同时显示真实
> AHT20 温湿度读数与曲线，且对传感器哈气时数值随之上涨。
>
> **噪声通道已于 2026-08-18 补齐验证**：HH_07.06 传感器到货并跑通 Modbus RTU 链路后，
> 三通道（温度/湿度/噪声）在手机端均正常显示，1 小时连续运行零丢帧、Modbus 应答成功率 100%；
> 断线自动重连亦已通过三种故障注入实测（最长恢复 32 s，与指数退避上限吻合）。
> 仍未测的只有**静默失连**场景（连接假死时的应用层 10 秒无数据健康检测）。
>
> **第二阶段的硬边界**（2026-08-16 当时）：`data/` 下四个文件与 `ServerConfig.kt` 一行未改，
> 未新增任何第三方依赖。连接状态六态、停滞检测全部由已有回调 + 一个 1 秒 tick
> 在 UI 层派生。

**没做**（有意为之）：历史数据（PC 端 `service`/`api` 尚无对应能力，不伪造、
不画假曲线——指标卡里的折线只是"本次连接以来 App 自己收到的点"，断开即清空）、
登录/用户系统、本地数据库、蓝牙、Android 直连 STM32。
