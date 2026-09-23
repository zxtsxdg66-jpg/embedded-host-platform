# web/ —— 浏览器控制台

网关（`src/gateway`）的又一个客户端，与 `android/` 同性质：只经 REST 与 WebSocket 通信，
不 import 任何 Python 符号，不进 `pytest`/`mypy src` 的范围，没有 npm 构建链。
设计与取舍见 [`docs/02_Architecture/Web_Console_Design.md`](../docs/02_Architecture/Web_Console_Design.md)。

## 四个页签

| 页签 | 内容 |
| --- | --- |
| 监测 | 三个通道的读数卡片（含越限状态、阈值）、滚动曲线、通风决策、设备列表 |
| 串口链路 | 链路计数（正常帧 / 重同步 / CRC 失败 / 帧格式错 / 忽略 / 载荷错）、事件流、单帧拆解（字段、声明 CRC 与浏览器重算 CRC-32 并列） |
| 环境问答 | 问答与**全过程追溯**：识别出的意图、取数层给出的事实、模板原句、每次模型改写及出口校验的判定（采纳 / 被哪条规则拦下） |
| 历史 | 从网关历史库（或回放数据）取一个通道的整段曲线 |

风扇模式与温湿度阈值只能在**实时模式**下修改；回放模式下这些控件置灰并写明原因。

## 三种打开方式

1. **由网关托管（实时）**：启动网关后浏览器打开 `http://<网关地址>:8000/web/`。

   ```bash
   python scripts/run_api_server.py --mode virtual --inject-faults   # 无需任何硬件
   python scripts/run_api_server.py --mode hardware --port-serial COM10
   python scripts/run_api_server.py                                   # simulator
   ```

   `--mode virtual` 在进程内跑一个虚拟 STM32，经无消息边界的字节管道接到**真实的**
   `HardwareDeviceReceiver`；加 `--inject-faults` 后它会拆帧、并帧、插杂散字节、翻转 CRC
   比特，串口链路页能看到主机侧逐个判出。`--no-web` 可关闭 `/web/` 挂载。
   串口链路页只在有字节流的模式（hardware / virtual）下有内容，simulator 模式没有链路。

2. **双击 `web/index.html`（file://）**：页面先尝试连 `http://127.0.0.1:8000`（或上次填过的地址），
   连不上就进入回放。所以全部脚本都是普通 `<script>`，不用 ES 模块——浏览器禁止 file:// 页面加载模块。

3. **GitHub Pages**：把 `web/` 作为站点根目录发布即可。页面识别到 `*.github.io` 就直接进入回放，不去探测网关。

## 回放数据

`replay/replay-data.js` 由脚本生成，不要手改：

```bash
python scripts/build_web_replay.py
```

它把原始记录送过**真实的**接收链路（帧重新编码 → 管道 → `HardwareDeviceReceiver` + `LinkMonitor`
→ `SensorDataProcessor` / `VentilationController` → `gateway.events` 的序列化函数），所以回放里的每条消息
与在线时 WebSocket 收到的格式完全相同。包含三段：

- `hour`：论文的一小时稳定性实验（3489 帧）。原始采集只存了读数没存字节，帧是按协议重新编码的。
- `faults`：虚拟 STM32 带故障注入的一段会话（固定随机种子），脚本会断言主机侧判出的重同步数
  等于注入的杂散字节数、CRC 失败数等于翻转数。
- `assistant`：`docs/05_Test/baseline/约束展示实录_*.json` 里的真实模型问答，含追溯。

## 文件

| 文件 | 职责 |
| --- | --- |
| `index.html` | 页面骨架 |
| `css/console.css` | 样式，深浅色两套变量 |
| `js/core.js` | 命名空间、工具函数、状态仓库 `EHP.Store`（唯一的数据入口 `handle(msg)`） |
| `js/chart.js` | 原生 Canvas 时间轴折线图 |
| `js/sources.js` | 两种数据源：`LiveSource`（REST + WebSocket，1→32 s 指数退避重连）与 `ReplaySource` |
| `js/views.js` | 各页签的渲染 |
| `js/main.js` | 启动、数据源切换、回放控制条 |
