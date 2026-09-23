# tests

目录与 `src/` 对应，另有 `integration/`（跨层端到端）、`architecture/`（依赖规则）、`scripts/`（启动器与工具）。

```bash
pytest                            # 全部，约 30 秒
pytest tests/protocol             # 单个目录
QT_QPA_PLATFORM=offscreen pytest  # 没有显示器的环境
```

`pyproject.toml` 设了 `pythonpath = ["src", "."]`，可以直接 `from protocol.encoder import ...` 与 `from scripts.run_gui import ...`。

测试策略、覆盖范围与各目录用例数见 [`docs/verification.md`](../docs/verification.md#自动化测试)，写测试的规矩见
[`CONTRIBUTING.md`](../CONTRIBUTING.md#先写测试)。

## 替身

只有物理资源用替身，自己的代码尽量用真的：

| 资源 | 做法 |
| --- | --- |
| 串口 | `tests/communication/test_serial.py` 的假串口，替换 `serial.Serial` 与端口枚举 |
| 真实字节流 | `communication.pipe` 的管道 + 虚拟设备 |
| 语言模型 | 脚本化的假客户端；模型客户端本身用抓下来的真实服务字节回放 |
| 云存储 | `tests/conftest.py` 自动兜底，任何测试都拿不到真实凭证 |
| 界面 | `pytest-qt` 离屏运行，后端是真实的运行时 |

## 每个目录下的空 `__init__.py` 不能删

有同名测试文件（三个 `test_interface.py`，分别在 `api/`、`communication/`、`device/`）。
pytest 默认的导入模式下，没有 `__init__.py` 时它们都叫 `test_interface`，第二个采集时报 `import file mismatch`。
有了它，模块名变成 `tests.api.test_interface` 等，各自独立。

容易误判的一点：**只删一个目录的 `__init__.py` 不会报错**，撞名需要两个目录同时缺失。所以"删了跑一遍没事"证明不了它没用。
