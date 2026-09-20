# device/sensors

## 职责

`device/sensors` 是"传感器应用模拟验证阶段"新增的子包，提供三个具体的环境监测传感器模拟设备，用于在真实 STM32 + 传感器到位前，验证数据处理链路（`SensorSimulator → DataService → SensorDataProcessor`）在一个具体、贴近真实场景（温度/湿度/噪音）下能否正确工作。

## 已实现

- `channels.py`：`TEMPERATURE_CHANNEL`/`HUMIDITY_CHANNEL`/`NOISE_CHANNEL` 三个通道名常量，供本子包与 `service/sensor_data_processor.py` 共用，避免字符串拼写不一致
- `generators.py`：两个新的 `ValueGenerator` 实现（**不修改** `device/simulator.py`，只是 import 其中的 `ValueGenerator` 基类）
  - `SmoothRandomWalkGenerator`：有界随机游走，每次调用只在当前值基础上做小幅扰动并夹紧到 `[low, high]`，用于模拟平滑/缓慢变化的读数（温度、湿度）
  - `NoiseWithSpikesGenerator`：大部分时间在基线区间取值，按概率短时跳到一个更高的峰值区间，用于模拟噪音传感器的"正常范围 + 偶发峰值"
- `temperature.py` / `humidity.py` / `noise.py`：`TemperatureSensorSimulator`/`HumiditySensorSimulator`/`NoiseSensorSimulator` —— 均为 `SimulatorDevice` 的**子类**（组合式扩展，不修改 `SimulatorDevice` 本身），只是预先配置好一个 channel 与对应的 domain-specific generator：
  - 温度：`channel="temperature"`，20~40℃，平滑变化
  - 湿度：`channel="humidity"`，40~80%，变化更缓慢（默认 `max_step` 更小）
  - 噪音：`channel="noise"`，正常 40~60dB，按概率产生 75~95dB 的短时峰值

## 设计约束

- **不修改** `device/simulator.py`（`SimulatorDevice`/`ValueGenerator` 均只被 import，未被改动）
- **不修改** `device/remote.py`（`RemoteDevice`）
- **不修改** `protocol`/`communication`/`api`/`ui`
- 三个 Sensor 类均保持 `DeviceInterface` 兼容（通过继承 `SimulatorDevice` 天然获得，未重新实现）
- 不在 `device/__init__.py` 中重新导出：顶层 `device` 包的定位是"不绑定具体传感器"的通用抽象，这三个具体传感器预设有意放在独立子包中，需要显式 `from device.sensors import TemperatureSensorSimulator` 才能使用

## 依赖关系

依赖 `core`、`device`（具体是 `device.simulator` 中的 `SimulatorDevice`/`SimulatedChannel`/`ValueGenerator`）。被 `service.sensor_data_processor`（仅依赖其 `channels.py` 常量，不依赖具体传感器类）间接引用。

## 相关文档

- `docs/02_Architecture/Core_Service_Design.md`（第 6 节 设备模拟器设计）
- `docs/05_Test/Hardware_Simulation_Mode.md`
