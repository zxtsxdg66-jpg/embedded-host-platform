# device/sensors

三个环境传感器的模拟预设，simulator 模式用它们在没有硬件时产生逼真的数据。

| 文件 | 内容 |
| --- | --- |
| `channels.py` | 通道名常量 `temperature` / `humidity` / `noise`，全项目（含固件）一致 |
| `generators.py` | `SmoothRandomWalkGenerator`：有界随机游走，模拟缓慢变化；`NoiseWithSpikesGenerator`：基线区间 + 按概率出现的短时峰值 |
| `temperature.py` / `humidity.py` / `noise.py` | 预配置好的 `SimulatorDevice` 子类：温度 20~40 ℃、湿度 40~80 %RH、噪声 40~60 dB 基线加 75~95 dB 峰值 |

都接受一个可选的随机数生成器：给定种子时整段数据可复现（虚拟设备的故障注入会话就靠它复现）。

不从 `device` 顶层导出：`device` 包本身不绑定具体传感器，要用须显式 `from device.sensors import ...`。
