package com.example.envmonitor.data

/**
 * Android 侧数据模型。
 *
 * 每个字段都对应 PC 端已有的真实类型，没有自行发明字段：
 *  - [DeviceStatus]  <- PC application.runtime.DeviceStatusView
 *  - [RealtimeData]  <- PC service.data_models.DataPoint（+ 服务端附加的 unit）
 *  - [AlarmStatus]   <- PC service.sensor_data_processor.ThresholdStatus
 *  - [Statistics]    <- PC service.sensor_data_processor.ChannelStatistics
 *
 * 其中 unit 是 PC 网关在推送时附加的展示字段（DataPoint 本身没有 unit），
 * 详见 docs/10_AndroidClient/PC_Android_接口设计.md 3.1 节。
 */

data class DeviceStatus(
    val deviceId: String,
    val isConnected: Boolean,
    val isOccupied: Boolean,
    val occupant: String?,
)

data class RealtimeData(
    val deviceId: String,
    val channel: String,
    val value: Double,
    val unit: String,
    val timestamp: String?,
    val valid: Boolean,
)

data class AlarmStatus(
    val deviceId: String,
    val channel: String,
    val value: Double,
    val unit: String,
    val threshold: Double,
    /** "ABOVE_MAX" / "BELOW_MIN" */
    val kind: String,
    val triggered: Boolean,
)

data class Statistics(
    val deviceId: String,
    val channel: String,
    val unit: String,
    val current: Double,
    val minimum: Double,
    val maximum: Double,
    val average: Double,
    val sampleCount: Int,
)

/**
 * 环境问答的一条回答。字段与 PC 端 service.assistant.models.Answer 的
 * text / source 两项对应（网关只暴露这两项，见 PC_Android_接口设计.md 2.8 节）。
 *
 * [source] 说明这句话由谁组织，四种取值与 PC 端 AnswerSource 一一对应：
 * "template"（规则 + 模板）、"model_intent"（模型判断了问题类别，句子仍是程序生成的）、
 * "model"（模型改写了措辞，数字仍来自程序且经过校验）、"fallback"（没听懂，给出会答什么）。
 * 数字在任何一种取值下都不来自模型——这是 PC 端的硬约束，客户端只负责如实展示是谁在说话。
 */
data class AssistantAnswer(
    val text: String,
    val source: String,
) {
    companion object {
        const val SOURCE_TEMPLATE = "template"
        const val SOURCE_MODEL = "model"
        const val SOURCE_MODEL_INTENT = "model_intent"
        const val SOURCE_FALLBACK = "fallback"
    }
}

/**
 * 一条历史读数。对应 PC 端 service.history.HistoryPoint，字段取自
 * `GET /devices/{id}/channels/{channel}/history` 的 points 数组
 * （见 PC_Android_接口设计.md 2.3 节）。
 *
 * [timestamp] 保留服务端给的 ISO-8601 原文而不在本地解析成时间对象，
 * 与 [RealtimeData.timestamp] 的处理一致：手机只负责显示，时刻的权威解释
 * 在 PC 端。服务端一律发 UTC（带 +00:00），显示时截取时分秒即可。
 *
 * 注意这里**没有 unit 字段**：单位是通道的属性不是读数的属性，
 * 服务端把它放在响应顶层，由 [HistoryPage] 持有。
 */
data class HistoryPoint(
    val value: Double,
    val timestamp: String?,
    val valid: Boolean,
)

/** 一次历史查询的完整结果：通道信息 + 该通道的若干条读数。 */
data class HistoryPage(
    val deviceId: String,
    val channel: String,
    val unit: String,
    val points: List<HistoryPoint>,
)

/** PC 端 device/sensors/channels.py 中定义的三个通道 id，必须与之保持一致。 */
object Channels {
    const val TEMPERATURE = "temperature"
    const val HUMIDITY = "humidity"
    const val NOISE = "noise"
}
