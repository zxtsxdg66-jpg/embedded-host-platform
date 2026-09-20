# storage

## 职责

本地**持久化存储**的接入适配器。与 `communication/`（设备接入）、`llm/`（模型服务接入）平级，三者都是"接外部资源的适配层"，只是接的资源不同：前两者分别对接串口与本地模型服务，本包对接磁盘。

新增该顶层包的动机、影响范围与替代方案取舍（为什么不放进 `application/` 或 `service/`），见 `docs/02_Architecture/History_And_Cloud_Design.md` 第 3.2 节。简短理由：让"谁可以碰外部资源"这条线保持一致——碰外部资源的都是顶层适配包，都不被 `service` import，都只在组合根创建。

## 已实现

- `sqlite_history.py`：`SqliteHistoryStore` —— 基于标准库 `sqlite3` 的历史读数存储
  - `append_many()` / `query()` / `query_range()` / `count()` / `close()`，满足 `service.history.HistoryStore`
  - 开 WAL，使网关查询与采集循环写入不互相阻塞
  - 只依赖标准库，无新增第三方依赖
- `export_ledger.py`：`SqliteExportLedger` —— 归档导出的台账（2026-09-17 新增，P2）
  - `record_export()` / `is_exported()` / `mark_uploaded()` / `pending_uploads()` / `all_records()` / `close()`
  - **与历史读数同一个 sqlite 文件、不同表**（用户 2026-09-17 确认）：分成两个文件的话，
    "导出了哪一段"与"那一段的数据"在崩溃或手工删档后会对不上
  - 幂等交给 `slot` 列上的 UNIQUE 约束，而不是"先查后插"——后者在并发下会双双查到"没有"

- `oss_uploader.py`：`OssUploader` + `OssConfig` + `load_config()` —— 阿里云 OSS 上传（2026-09-17 新增，P3）
  - 凭证只从项目根的 `oss_config.json` 读，**不硬编码**；该文件不进仓库
  - `OssConfig.__repr__` **被刻意重写**：dataclass 默认会把所有字段打出来，而它带着 AccessKey Secret——一次无心的 `print(config)` 或异常回溯就够把密钥写进日志
  - `load_config()` 同时拒绝空值与**含星号的占位**：示例文件里的 `LTAI************` 不是空串，只查空值会把它当成有效配置放行，于是照抄示例却忘了填的人撞到的是一个莫名的鉴权错误，而不是"你还没填凭证"
  - **惰性连接**：构造时不碰网络，第一次真正上传才建 `oss2.Bucket`，所以"没配 OSS"与"配了但断网"都不会让脚本在启动时就失败
  - 依赖 `oss2`，声明在 `pyproject.toml` 的 `cloud` 可选组里——`src/` 与 `tests/` 缺了它都能跑通

### `query()` 与 `query_range()` 的顺序是相反的

前者**新的在前**（喂界面，人关心刚发生了什么），后者**由早到晚**（喂导出文件，人从上往下顺着时间读）。
让存储定顺序，省得每个调用方各自重排；但这个不对称确实容易踩，所以两处 docstring 与用例都把它钉住了。

## 设计约束

- **不依赖 `service` 的实现**：`HistoryStore` 协议定义在消费方 `service.history`，本包的类靠结构化匹配（鸭子类型）满足它，由 mypy 在 `application`/`scripts` 的装配点验证。与 `LlmClient` 定义在 `service.assistant.llm_port`、`CommandTransport` 定义在 `service.control_service_impl` 是同一条既有约定。
  - 本包确实 import `service.history` 里的 `HistoryPoint` 数据类，那是共享的数据模型而非实现，与 `api` 依赖 `core`/`service` 共享模型类型同性质。
- **绝不向调用方抛异常**：磁盘满、文件被锁、库损坏都不该把采集循环带下去。失败被计数并记下原因（`failures` / `last_error`），供启动器显示"历史没有在写"——否则这类故障是完全无声的。
- **只能在 `application/` 或 `scripts/` 中被创建**，与 `SerialChannel`、`OllamaClient` 同一条规矩。

## 时间戳为什么存 UTC 文本

`DataPoint.timestamp` 本身就是 `core.timestamps.now_utc()`。原样存下来，导出与跨时区读取时都不必猜测基准；给人看的本地时间由导出环节另加一列，那是呈现问题，不是存储问题。

## 无效读数为什么照存

固件在 Modbus 读取失败时**根本不上报**噪声通道，因此真的到达上位机的无效读数是链路质量的证据。在入口处过滤掉，这份证据就再也补不回来了。
