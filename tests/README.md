# tests

测试目录结构与 `src/` 一一对应（另加 `integration/` 与 `scripts/` 两个目录），测试策略与各层验证手段见 [`docs/05_Test/Test_Plan.md`](../docs/05_Test/Test_Plan.md)，本文只讲目录结构与怎么跑；pytest 用法遵循 `.claude/skills/testing-python-libraries` 的规范。

当前共 **1278 个用例，全部通过**（2026-09-18 末次实测）。用例随各模块功能实现同步添加，新增功能应同时补充对应测试。

## 目录与用例分布

| 目录 | 用例数 | 对应模块 | 对应 Test_Plan.md 小节 |
| --- | --- | --- | --- |
| `tests/core/` | 13 | `src/core/` | — |
| `tests/protocol/` | 28 | `src/protocol/` | 协议层 |
| `tests/communication/` | 40 | `src/communication/` | 通信层 |
| `tests/device/`（含 `sensors/`） | 76 | `src/device/` | 各层验证手段（设备抽象部分） |
| `tests/service/` | 316 | `src/service/`（含 `assistant/` 子包） | 服务层 |
| `tests/application/` | 144 | `src/application/` | 应用层 + 跨端契约 |
| `tests/api/` | 36 | `src/api/` | 接口层与呈现层 |
| `tests/gateway/` | 29 | `src/gateway/` | 接口层与呈现层 |
| `tests/ui/` | 189 | `src/ui/` | 接口层与呈现层 |
| `tests/integration/` | 32 | 跨层端到端链路 | 总体策略 |
| `tests/llm/` | 19 | `src/llm/` | —（Ollama 客户端，用假 socket 回放真实服务字节） |
| `tests/storage/` | 59 | `src/storage/` | —（SQLite 历史库、导出台账、OSS 上传器，均不碰网络） |
| `tests/scripts/` | 172 | `scripts/` 组合脚本与工具（含 `start_llm`/`stop_llm`、`question_log`） | 组合脚本 |
| **合计** | **1153** | | |

复现该表：`QT_QPA_PLATFORM=offscreen pytest --collect-only -q`（按目录汇总各文件计数）。

## 每个目录下的空 `__init__.py` 不能删

上表每个目录（连同 `tests/` 自身、`device/sensors/`、`service/assistant/`）下都有一个
**0 字节的 `__init__.py`**。它看起来是遗留文件，实际是**必需的**。

原因是仓库里存在同名测试文件——目前有三个 `test_interface.py`
（`api/`、`communication/`、`device/` 各一）。pytest 默认的 `prepend` 导入模式下，
模块名从「最近一个不含 `__init__.py` 的祖先目录」开始算：没有它，两个文件都叫
`test_interface`，第二个采集时直接报错：

```
import file mismatch:
imported module 'test_interface' has this __file__ attribute:
  tests\api\test_interface.py
which is not the same as the test file we want to collect:
  tests\communication\test_interface.py
```

有了它，模块名变成 `tests.api.test_interface` 与 `tests.communication.test_interface`，
各自独立。**空文件本身就是内容：存在即声明"这是一个包"。**

有一点容易误判：**只删一个目录的 `__init__.py` 不会报错**，因为撞名需要两个目录同时缺失。
2026-09-10 实测过——单删 `api/` 的，三个 `test_interface.py` 照常全绿；同时删掉
`api/` 与 `communication/` 的才复现上面那个错误。所以"删了跑一遍没事"证明不了它没用。

同日补上了 `tests/gateway/__init__.py`——此前 15 个目录里只有它没有。当时不报错，
只是因为它里面两个文件恰好不与别处重名；一旦往里加一个 `test_models.py` 之类，
错误信息会指向另一个目录的文件，排查方向天然是错的。

## 运行方式

```bash
pytest                          # 全量；配置见 pyproject.toml 的 [tool.pytest.ini_options]
pytest tests/protocol           # 单个目录
QT_QPA_PLATFORM=offscreen pytest  # 无显示环境（CI/远程）下运行 PyQt6 测试时需要
```

`pyproject.toml` 已设置 `pythonpath = ["src", "."]`，因此既可以 `from protocol.encoder import ...`，也可以 `from scripts.run_gui import ...`，无需先 `pip install -e .`。

测试依赖装在 dev 可选依赖组里：`pip install -e ".[dev]"`（`pytest`、`pytest-qt`、`httpx` 等）。

## 无真实硬件条件下的测试手段

- **串口**：`tests/communication/test_serial.py` 用 `_FakeSerialPort`（只实现 `SerialChannel` 真正用到的 `is_open`/`write`/`in_waiting`/`read`/`close`）配合 `unittest.mock.patch` 替换 `serial.Serial` 与 `list_ports.comports()`，覆盖端口不存在、打不开、写超时、读异常等真实硬件上难以稳定复现的场景。`tests/scripts/test_run_gui.py` 复用同一手法测硬件模式装配。
- **PyQt6 界面**：用 `pytest-qt` 的 `qtbot`。界面测试不 mock 后端——`test_main_window.py` 构造真实的 `ApplicationRuntime` + `LocalApi` + `SimulatorDevice` + `LoopbackChannel` 栈，一条用例跑完"设备生成 → 编帧 → 回环通道 → 解帧 → 发布 → Qt 信号 → 控件更新"整条链路。
- **网关**：`tests/gateway/test_server.py` 用 FastAPI 的 `TestClient` 在进程内跑真实 ASGI 应用（真实路由、序列化、WebSocket 握手），API 层不做任何 mock。
- **硬件在环**：需要真实串口字节流的验证由 `scripts/virtual_stm32.py` 配合虚拟串口对完成，不属于 pytest 范围，见 `docs/05_Test/Virtual_STM32_Test.md`。

## 测试原则（摘自 `.claude/skills/testing-python-libraries`）

- 独立：测试之间不共享状态
- 确定性：多次运行结果一致
- 快速：单元测试单条应 < 100ms
- 聚焦：测试行为而非实现细节

## 任务收尾检查

每个开发任务收尾前应跑完以下三项且全绿（见 `CLAUDE.md`）：

```bash
pytest
ruff check src tests scripts
mypy src
```
