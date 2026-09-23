# api

`ApiInterface`：所有呈现端（桌面界面、网关）访问系统的唯一入口。

| 文件 | 内容 |
| --- | --- |
| `interface.py` | `ApiInterface`：设备与状态、数据订阅、控制权与命令、报警与统计订阅、通风、问答、历史、链路统计 |
| `local_api.py` | `LocalApi`：本进程内的实现，委托给 `ApplicationRuntime`，并把下层异常转译成 `api` 的异常 |
| `exceptions.py` | `DeviceNotFoundError`、`CommandAuthorityError`、`CommandDeliveryError` 等 |

几条约定：

- **只增不改。** 新能力以新增方法的形式加入，不改已有方法的签名
- 对外暴露的模型类型（`DataPoint`、`Command` 等）就是 `service` 里的那些，不在这里重新定义。
  呈现端可以 import 的 `service` 模块，正是这个接口的签名里出现的那几个（由依赖规则测试核对）
- `ask()` 同步返回模板答案（纯计算，毫秒级），不等模型；也不做异常转译——"没听懂""暂时没有数据"是正常答案，不是错误

依赖：`core`、`application`、`service`（模型类型）。
