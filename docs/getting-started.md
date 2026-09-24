# 上手

## 安装

```bash
pip install -e ".[dev]"          # 运行 + 测试
pip install -e ".[dev,cloud]"    # 另外需要归档上云时
```

Python 3.10 及以上。依赖只有 PyQt6、pyserial、FastAPI/uvicorn 四个运行期包，其余都是可选组。

验证环境：

```bash
pytest                           # 全部测试，无需硬件、无需网络、无需模型
ruff check src tests scripts
mypy src
```

测试里所有碰串口的地方都用假串口替身，碰云存储的地方有自动兜底，
**不可能**在跑测试时连上真实设备或公网（`tests/conftest.py`）。

## 四种运行方式

数据从哪里来决定了运行模式。三种数据源从 `DataService` 往上用的是完全相同的代码，
差别只在最底下两层（原因见 [`architecture.md`](architecture.md#三种运行模式同一套上层代码)）。

| 模式 | 数据源 | 走真实的拼帧/CRC 链路吗 | 需要什么 |
| --- | --- | --- | --- |
| simulator | 进程内模拟设备 | 否（回环通道保留消息边界） | 什么都不要 |
| virtual | 进程内虚拟 STM32，经字节管道 | **是** | 什么都不要 |
| hardware | 真实 STM32，经串口 | **是** | 开发板与传感器 |

### 1. 桌面界面 + 模拟数据

```bash
python scripts/run_gui.py
```

注册三个模拟传感器（温度 20~40 ℃ 平滑随机游走、湿度 40~80 %RH、噪声 40~60 dB 基线加短时峰值），
每秒一轮。指标卡、曲线、统计、报警、通风、问答全部可用。

### 2. 网关 + 浏览器控制台（无硬件，但走真实接收链路）

```bash
python scripts/run_api_server.py --mode virtual --inject-faults
```

浏览器打开 <http://127.0.0.1:8000/web/>。进程内的虚拟 STM32 按真实固件的 3 s 周期发帧，
经一条**没有消息边界**的字节管道送进与硬件模式完全相同的接收器。`--inject-faults` 让它按概率
拆帧（25%）、并帧（30%）、插杂散字节（10%）、翻转 CRC 比特（3%）；控制台的"串口链路"页能看到每一处被判出。

去掉 `--inject-faults` 就是规规矩矩的虚拟设备；`--mode simulator`（默认）则用模拟设备、没有字节流。

### 3. 真实硬件

```bash
python scripts/run_gui.py --mode hardware --port COM7
python scripts/run_api_server.py --mode hardware --port-serial COM7
python scripts/run_all.py --mode hardware --port-serial COM7     # 桌面界面与网关同进程
```

- 波特率默认 115200，与固件一致；`--baudrate` 可改
- 串口不存在时启动前就报错退出，被占用时给出中文提示，不会静默卡住
- **串口是独占资源**：桌面界面和网关要同时看数据，只能用 `run_all.py` 在一个进程里同时承载两者，
  不能分别启动两个程序去抢同一个 COM 口。数据只解码一次，再扇出给两边

**在真实硬件上验证链路可靠性**：

```bash
python scripts/run_api_server.py --mode hardware --port-serial COM7 --inject-faults
python scripts/run_all.py --mode hardware --port-serial COM7 --inject-faults --fault-length --fault-seed 1
```

真实串口几乎不出错，所以在上位机收到的字节流里按已知数量制造故障（拆帧、并帧、杂散字节、翻转 CRC），
每分钟打印一行对账，退出时打印完整结果：判出的次数应与注入的次数逐项相等，且没有任何被破坏的帧被当作读数接受。
`--fault-length` 另外翻转长度字段，实测那个已知缺陷；`--fault-seed` 固定随机种子。
原理见 [`verification.md`](verification.md#在真实硬件上注入)。

**现场演示报警**：室内很少真的越限，屏幕上的"报警"平时看不到。

```bash
python scripts/demo_alarm.py --temperature-max 20 --mode hardware --port-serial COM7
```

临时把温度报警上限调到当前读数以下（数值取比室温低一点），再原样启动桌面界面加网关；
开发板屏幕在一两个采集周期内变"报警"并播报一次语音，60 秒后（`--for` 可改）自动恢复为"正常"。
不改任何源文件，只改内存里的阈值表，退出时同样恢复。

### 4. 手机

用 `run_api_server_手机网关.bat` 或 `run_all_界面加网关.bat` 启动，它们会打印本机局域网地址，
在 Android 客户端里填上即可（手机与电脑在同一 Wi-Fi 或热点下）。
Android 工程在 `android/`，用 Android Studio 打开。

## Windows 启动器

根目录的 `.bat` 可以直接双击，会交互式地问模式、列出串口并标出最像开发板的那个
（按 USB 转串口芯片特征判断，排除蓝牙虚拟串口——很多电脑没插板子时就已经有几个串口了）。

| 启动器 | 做什么 |
| --- | --- |
| `run_gui_模拟数据界面.bat` | 桌面界面，模拟数据 |
| `run_gui_hardware_真实硬件界面.bat` | 桌面界面，真实硬件（交互选串口） |
| `run_api_server_手机网关.bat` | 只起网关，供手机和浏览器连接 |
| `run_all_界面加网关.bat` | 桌面界面 + 网关同进程，共用一条串口 |
| `collect_data_实验数据采集.bat` | 实验数据采集，输出原始 CSV 与统计表 |
| `start_llm_启动本地模型.bat` / `stop_llm_停止本地模型.bat` | 拉起并预热本地模型 / 卸载模型释放内存 |
| `cloud_sync_导出并上传.bat` | 把已结束的整点时段导出为 CSV 并上传 |
| `cloud_snapshot_上传当前时段快照.bat` | 同上，另把"当前这一小时到现在"截一份快照上传 |
| `cloud_view_查看云端.bat` | 只读查看云上已有文件 |

## 可选组件

### 本地语言模型

问答的意图识别与措辞改写可以接一个本地 [Ollama](https://ollama.com) 模型（开发时用 `qwen3.5:4b`）。
启动脚本会探测一次，**探测不到就照常运行**，只是答案全部来自模板。

```bash
python scripts/run_all.py --llm-model qwen3.5:4b
python scripts/run_all.py --no-llm
```

模型冷启动首次推理要从磁盘载入约 3.4 GB，`start_llm` 启动器会发一次真实请求预热，把这段等待挪到开始之前。

### 历史与归档上云

运行期间读数写入本地 SQLite 历史库（`data/`，不入库）。上云是**手动触发**的：
双击 `cloud_sync` 启动器才导出并上传，没有定时器、后台线程或上传队列。
凭证放在 `oss_config.json`（参照 `oss_config.example.json`，已被 `.gitignore` 排除）。

### 实验数据采集

```bash
python scripts/collect_experiment_data.py --port COM7 --duration 3600 --label 长时间稳定性
python scripts/collect_experiment_data.py --from-csv experiment-data/<文件>.csv --label 复算
```

采集走的是系统自己的接收链路（`SerialChannel` → `HardwareDeviceReceiver`），不另写一份解析；
第二行用已有的原始数据重新出统计表。

## 常见问题

| 现象 | 原因 |
| --- | --- |
| `PermissionError(13, '拒绝访问。')` | 串口被别的程序占着：另一个上位机进程、串口助手 |
| 订阅了但一直没数据，也没报错 | 选错了串口（常见是蓝牙虚拟串口），或波特率与固件不一致 |
| 手机连不上网关 | 手机与电脑不在同一网络；电脑防火墙拦了 8000 端口；路由器开了 AP 隔离 |
| 问答回答得很慢 | 本地模型冷启动，先运行 `start_llm` 预热 |
