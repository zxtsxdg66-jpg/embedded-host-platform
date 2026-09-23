# storage

本地持久化与对象存储。与 `communication`（接串口）、`llm`（接模型服务）同为"接外部资源的适配层"。
设计取舍见 [`docs/decisions/06-history.md`](../../docs/decisions/06-history.md)。

| 文件 | 内容 |
| --- | --- |
| `sqlite_history.py` | `SqliteHistoryStore`：历史读数，标准库 `sqlite3`，开 WAL（网关查询与采集写入互不阻塞） |
| `export_ledger.py` | `SqliteExportLedger`：归档导出台账，与历史读数同一个库、不同表。幂等交给唯一约束，而不是"先查后插" |
| `oss_uploader.py` | `OssUploader`：阿里云 OSS 上传，惰性连接；依赖 `oss2`（可选依赖组 `cloud`） |

几个细节：

- **失败计数不抛。** 磁盘满、文件被锁不该把采集循环带下去；失败次数与最后一次原因可查询，故障不是静默的
- **时间戳存 UTC 文本**，给人看的本地时间在导出时另加
- **`query()` 新的在前、`query_range()` 由早到晚**：前者喂界面，后者喂导出文件。顺序由存储决定，两处都有测试钉住
- **凭证只从 `oss_config.json` 读**，不硬编码；配置对象的 `repr` 被刻意重写，不会把密钥打进日志；
  示例文件里带星号的占位值会被拒绝，而不是被当成有效配置去撞一个莫名的鉴权错误
- `HistoryStore` 协议定义在 `service/history.py`；只能在 `application` 或 `scripts/` 中创建

依赖：`core`、`service`（`HistoryPoint` 数据类）、标准库；上传另需 `oss2`。
