# core

## 职责

`core` 是跨层共享的基础设施模块，对应 `docs/02_Architecture/Software_Structure.md` 中 `src/common/` 的职责定义，为 `device`、`communication`、`protocol`、`service`、`api`、`ui` 等模块提供统一的底层支撑。

预期包含（不在本次初始化中实现）：

- **logging**：统一日志配置与格式规范，遵循 `docs/04_Development/Coding_Standards.md` 中的日志分级要求
- **config**：应用配置的加载与管理
- **exceptions**：跨层复用的自定义异常基类，遵循 `docs/04_Development/Coding_Standards.md` 中"禁止裸 except、异常语义清晰"的要求
- **types / common models**：不属于某一具体层、但被多层复用的通用类型定义

## 依赖关系

`core` 不依赖本项目中的任何其他模块，可被所有其他模块依赖。

## 相关文档

- `docs/02_Architecture/Software_Structure.md`
- `docs/04_Development/Coding_Standards.md`

## `channel_display.py`（2026-09-18 新增）

通道的展示约定：中文名、单位、小数位。**全项目唯一定义处**，`ui`、`gateway`
与归档导出脚本三处共用。

放在 `core` 而不是某个呈现端，是因为呈现端不止一个：`ui/channel_display.py`
与 `gateway/channel_units.py` 曾各存一份，靠注释提醒人手动同步，而手动同步
在 2026-09-18 当天刚失败过一次——手机端与桌面端的小数位对不上，同一条读数
显示成 25.0 与 25.03，返工重打了一次 APK。`gateway` 不能直接 import
`ui/channel_display.py`，因为 `import ui.*` 会执行 `ui/__init__.py` 并把
PyQt6 整个拉进来，无界面服务不该依赖 GUI 框架。

**它仍然只是展示约定，不是协议的一部分。** `protocol`/`communication`
不得据此做任何判断；线上传的是 channel id。放进 `core` 是为了让几个呈现端
共用一份定义，不是把展示文本降到传输层。
