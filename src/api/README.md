# api

## 职责

`api` 是 `application.ApplicationRuntime` 面向外部调用方（本地客户端接口、未来网关模式下的网络 API）的统一访问门面，对应 `docs/02_Architecture/Core_Service_Design.md` 第 8 节"后续 API 接口扩展方向"与 `docs/02_Architecture/Multi_Client_System_Architecture.md` 第 5 节"PC 端和 Android 端调用关系"。

已实现（第一阶段）：

- `interface.py`：`ApiInterface` —— 统一抽象入口（查询设备列表/状态、数据订阅、控制权获取/释放、提交指令、查询指令结果、阈值报警状态订阅 `subscribe_alarm_status`、统计信息订阅 `subscribe_statistics`——后两个均 2026-08-12 新增，均为全局订阅、无配套 unsubscribe）
- `local_api.py`：`LocalApi` —— `ApiInterface` 的本地直连模式实现，纯粹委托给注入的 `ApplicationRuntime`，并将底层通用的 `NotFoundError`/`StateTransitionError`/`OperationTimeoutError` 转译为更具体的 `api.exceptions` 类型
- **通风控制（2026-09-07 新增，扩展本受保护接口已获用户明确授权，纯增量、未改动任何既有方法签名）**：`get_ventilation_settings`/`set_ventilation_thresholds`/`set_fan_mode`/`subscribe_fan_decision`。注意这里的通风阈值**不是**阈值报警的限值——后者取自 GB 37488—2019、论文已论证、固定不变；前者是另一套语义不同且可运行时调整的限值，原因见 `src/service/ventilation_controller.py` 模块注释。`tests/api/test_interface.py` 中有一条守卫测试锁定本接口的抽象方法集合，扩展接口时必须同步更新它——这正是该测试存在的意义
- `exceptions.py`：`ApiError` 及其子类（`DeviceNotFoundError`/`CommandNotFoundError`/`CommandAuthorityError`/`CommandDeliveryError`——最后一个只在 Hardware 模式下可能触发，对应 `DeviceManager.deliver()` 等待设备应答超时的情形，见 `docs/05_Test/Hardware_Simulation_Mode.md`）

尚未实现（不在本次范围内）：

- 网关模式下的网络 API（候选：REST/RPC 用于设备查询与指令下发，WebSocket 用于数据订阅推送），详见 `docs/02_Architecture/Multi_Client_System_Architecture.md` 第 2.2 节
- 指令权限模型的扩展（当前仅有"共享读、独占写"这一基线规则）

## 设计约束

- **只作为 `ApplicationRuntime` 的访问门面**：不直接 import `device`、`communication`、`protocol`，不在本层实现任何设备/通信/协议逻辑
- 对外暴露的概念模型（`Device` 状态、`DataPoint`、`Command`/`CommandResult`）与 `service`/`application` 中定义的完全一致，不重新定义业务概念
- 不绑定 PyQt、不绑定 Android：`api` 本身不包含任何界面代码

## 依赖关系

依赖 `core`、`service`（仅复用其 Command/CommandResult/DataPoint/DataCallback 等共享概念模型类型）、`application`（唯一的功能委托对象）。不依赖、也不被 `communication`、`protocol`、`device` 依赖。

## 相关文档

- `docs/02_Architecture/Core_Service_Design.md`（第 8 节）
- `docs/02_Architecture/Multi_Client_System_Architecture.md`（第 2.2、6.3 节）

## `ask()`（2026-09-08 新增，经用户授权扩展受保护接口）

环境问答的入口。**之所以必须放在这一层**：`src/ui/*` 只能 import `src/api`，聊天面板没有别的路径能触到助手。助手本体在 `service.assistant`。

同步返回，因为意图识别与模板渲染都是纯计算、没有 I/O——实测 22 毫秒。语言模型的改写**不在这里等**：它要几秒，`ask()` 立刻返回模板答案，改写结果由组合根经 `MainController.deliver_assistant_answer()` 迟到推入。

**没有**为取回改写结果再加第二个接口方法（如 `poll_assistant()`）：轮询是组合根才需要知道的事，界面只需要"有新答案时告诉我"。为一个只有启动器关心的机制加宽受保护接口，代价大于收益。

不做异常翻译——这是它与本文件其它方法的区别。"没听懂"和"暂时没有数据"都是**正常答案**而不是错误：聊天面板拿到异常没有任何有用的处理方式，但拿到这两句话可以直接显示。
