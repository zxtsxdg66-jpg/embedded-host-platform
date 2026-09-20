# Python 开发规范

> 本规范约束 `src/`、`tests/`、`scripts/` 下的全部 Python 代码。
> **下列约束不是建议，而是每个任务收尾前由工具实际检查的**——`ruff` 与 `mypy` 不过就不算完成。
>
> 2026-09-09 按实际工具链更新。上一版写于编码开始之前（"当前阶段仅作为后续开发的约束参考"、
> "具体工具选型在编码阶段确定"），且引用了一个从未存在过的目录 `src/common/exceptions/`。

## 工具链与收尾检查

| 工具 | 命令 | 配置位置 |
| --- | --- | --- |
| `ruff` | `ruff check src tests scripts` | `pyproject.toml` |
| `mypy` | `mypy src` | `pyproject.toml`：`disallow_untyped_defs` + `warn_return_any` + `warn_unused_ignores`（非 `strict`，但公开函数必须有完整标注） |
| `pytest` | `pytest` | `pyproject.toml`，`pythonpath = ["src", "."]` |

另有两项针对本项目特有风险的检查，动过对应部分时才需要跑：
`python scripts/check_keil_project.py`（改过固件）、
`python scripts/check_doc_numbers.py`（改过规模数字）、
`python scripts/check_doc_links.py`（改过文档结构）、
`python scripts/check_doc_identifiers.py`（改过公开名字；输出需人过目，框架名会误报）。

依赖装在 dev 可选依赖组里：`pip install -e ".[dev]"`。
**禁止自动安装依赖包**，需用户在当次任务中明确授权（见 `CLAUDE.md`）。

## Python 版本

- **目标版本 3.10+**：`ruff` 的 `target-version = "py310"`、`mypy` 的 `python_version = "3.10"`
  都锁在这里；开发机当前跑的解释器是 3.14，`.venv-wsl` 下另有一个 3.12 用于 Linux 侧串口测试。
  **写代码时按 3.10 的语法上限来**，不要用更新的特性。
- 联合类型写 `X | None` 而不是 `Optional[X]`，
  内置泛型写 `list[str]` 而不是 `List[str]`，模块首行一律 `from __future__ import annotations`

## 类型提示（Type Hints）

- 所有公开函数、方法的参数与返回值必须提供类型标注
- 涉及跨层调用的数据结构（如协议帧、设备状态）应使用明确的类型定义（如 `dataclass`、`TypedDict` 或自定义类），禁止使用裸 `dict` / `tuple` 传递结构化数据
- 复杂类型用 `collections.abc` 的 `Callable`/`Sequence`/`Iterator` 等标注，避免隐式的 `Any`
- **`mypy src` 必须零问题**。跨层传递的结构一律用 `@dataclass(frozen=True)`，
  这也是 `Facts` 把字段逐个显式声明、不用 `dict[str, Any]` 的原因——
  接地校验要枚举它们，而 `dict` 会同时废掉 mypy 和那道校验

## 异常处理

- 禁止使用裸 `except:` 捕获所有异常；必须指定明确的异常类型
- 通信、协议解析等边界处应捕获预期内的异常（如超时、校验失败），并转换为项目自定义的异常类型向上抛出，不应向上层暴露底层库的原始异常
- 禁止用异常吞没错误（即捕获后不处理、不记录、直接 `pass`）
- 自定义异常集中定义在 **`src/core/exceptions.py`**（跨层共享）与 `src/api/exceptions.py`
  （面向调用方的转译层），并具备清晰的语义命名
- **边界处不得让底层异常穿透**：`api` 层负责把下层异常转译成 `ApiError` 族；
  三个 dispatcher 则一律"记录不抛"——一次屏幕刷新失败不值得把轮询循环带走

## 日志规范

- 统一使用标准的日志机制（如 `logging` 模块），禁止使用 `print` 进行调试信息输出
- 日志需分级别记录：
  - `DEBUG`：详细的调试信息（如原始字节流）
  - `INFO`：关键流程节点（如连接建立、断开）
  - `WARNING`：可恢复的异常情况（如校验失败、重连中）
  - `ERROR`：影响功能的错误
- 日志内容应包含足够的上下文（如设备ID、通信方式），便于问题定位
- 禁止在日志中输出可能涉及敏感信息的内容（如有）

## 命名规范

- 遵循 PEP 8 命名约定：
  - 模块/文件名：`snake_case`
  - 类名：`PascalCase`
  - 函数/方法名、变量名：`snake_case`
  - 常量：`UPPER_SNAKE_CASE`
- 命名应清晰表达职责，避免使用无意义的缩写（如 `mgr`、`tmp` 等，除非在极小作用域内）
- 与架构分层相关的命名应体现所属层次（如通信实现类以通信方式为前缀/后缀命名）

## 注释要求

- 公开的类、方法应有简要说明其职责的文档字符串（docstring），不需要长篇大论，说明"做什么"和关键约束即可
- 代码注释应解释**为什么这样做**（如某个特殊处理是为了兼容某设备的已知问题），而非重复描述代码本身在做什么
- 协议相关的编解码逻辑，如涉及非直观的字节序、偏移量等，必须添加注释说明依据（对应协议文档中的具体条款）

## 注释里该写什么（本项目反复验证过的一条）

`docstring` 与注释的价值集中在**记录当初为什么这么选**，尤其是那些"看起来多余、
删掉也能跑"的代码。本项目里被真实翻查过的注释，几乎全是这一类：

- 为什么 dispatcher 要"记录—下发"分离（因为在回调里下发会重入串口，实测把进程打崩）
- 为什么模型只输出标签而不输出 JSON（4B 模型格式稳定性不够）
- 为什么负数读数拒发而不回绕（固件侧字段无符号，会被满有把握地画出来）

**写清楚这一层，后来的人才不会"顺手简化掉"一处防线。**

## 其他约束

- 遵循 `Development_Rules.md` 中定义的架构与模块化约束，以及 `CLAUDE.md` 的分层禁令
- 行宽 88（`ruff` 强制）；`ruff` 启用的规则集为 `E,W,F,I,B,C4,UP`（含 import 排序 `I`，
  因此不要手工调整 import 顺序，交给 `ruff check --fix`）
