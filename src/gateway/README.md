# gateway

无界面的 REST + WebSocket 网关，给 Android 客户端与浏览器控制台用。接口列表见
[`docs/android.md`](../../docs/android.md#网关接口)，设计取舍见 [`docs/decisions/07-gateway.md`](../../docs/decisions/07-gateway.md)。

| 文件 | 内容 |
| --- | --- |
| `server.py` | `create_app()`：FastAPI 应用。每个端点都是一个已有 `ApiInterface` 方法的直译，不写业务逻辑 |
| `event_hub.py` | `EventHub`：把采集线程上的同步回调桥接到 asyncio 的 WebSocket 发送；每个客户端一条有界队列，慢客户端只丢自己的消息 |
| `events.py` | WebSocket 消息的序列化 |
| `channel_units.py` | 通道单位，取自 `core.channel_display` |

约束：

- 只 import `api`、`core` 与 `api` 签名里出现的模型类型；**不依赖 PyQt6**，不 import `ui`
- `EventHub.publish()` 永不抛异常：它在数据管线上被同步调用
- 订阅哪些通道由组合根传入（`subscriptions` 参数），网关不自己发现
- 网关不知道 `web/` 的存在：页面由启动脚本挂载到 `/web/`

没有鉴权与传输加密，CORS 宽松放行，前提是局域网可信环境。
