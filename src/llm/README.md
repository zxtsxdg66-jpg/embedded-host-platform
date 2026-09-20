# llm

## 职责

外部**语言模型服务**的接入适配器。与 `communication/`（设备接入层）平级，但不是同一件事：后者与设备收发字节、向上给 `protocol`；本包与本地模型服务对话、向上给 `service.assistant` 文本。

新增该顶层包的动机、影响范围与替代方案取舍（为什么不并入 `communication/` 或 `application/`），见 `docs/02_Architecture/Assistant_Design.md` 第 4.1 节。

## 已实现

- `ollama.py`：`OllamaClient` —— 本地 Ollama 服务的**非阻塞**客户端
  - `submit()` / `poll()` / `is_busy()` / `cancel()`，由组合根的轮询循环驱动
  - `probe()`：启动时探测一次服务是否可达
  - 只依赖标准库

## 设计约束

- **不依赖 `service`**：`LlmClient` 协议定义在消费方 `service.assistant.llm_port`，本包的类靠结构化匹配（鸭子类型）满足它，由 mypy 在 `application`/`scripts` 的装配点验证。与 `CommandTransport` 定义在 `service.control_service_impl` 的既有约定一致。
- **绝不向调用方抛异常**：服务未安装、拒绝连接、超时都是本功能的正常状态——助手退回模板答案，那个答案本来就是对的。
- **只能在 `application/` 或 `scripts/` 中被创建**，与 `SerialChannel` 等具体通信对象同一条规矩。

## 为什么是非阻塞轮询而不是线程

PC 侧是完全同步单线程的（`QTimer → poll_once()`，无 QThread 无 asyncio），而纯 CPU 跑 4B 模型一次要几秒——任何阻塞调用都会把界面冻住那么久。所以采用与项目其它部分一致的非阻塞轮询形态，与固件里 `noise_sensor_poll()` 的非阻塞请求-应答是同一个模式。

之所以不用 `httpx`（项目已有，但仅 dev 依赖）：它的流式读取仍然阻塞调用线程，不加线程解决不了冻结问题。既然要自己做非阻塞，标准库就够了。

## 传输细节

Ollama 的 `/api/generate` 流式响应是 `Transfer-Encoding: chunked` 包着 `application/x-ndjson`，两层都在 `ollama.py` 里解。这个格式是**先抓真实字节确认过的**，不是照文档猜的——测试里的字节样本就是抓下来的那份。

## 缓冲而非逐字上抛

客户端内部消费流式分片（以便判定完成与超时），但**响应完整之前不向调用方交付任何文本**。两个原因见 `ollama.py` 模块注释，其中关键一条：截断的句子（如"噪声现在 76.3dB，一切正"）会**通过** grounding 检查并被当作答案显示出来，只交付完整响应从根上消除了这个失败模式。
