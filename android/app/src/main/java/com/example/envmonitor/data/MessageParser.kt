package com.example.envmonitor.data

import org.json.JSONException
import org.json.JSONObject

/**
 * 把 PC 网关推来的 WebSocket JSON 文本解析成数据模型。
 *
 * 刻意做成**不依赖任何 Android API** 的纯 Kotlin 对象（只用 org.json），
 * 这样它可以在普通 JVM 单元测试里直接跑——不需要模拟器、不需要真机。
 * [GatewayWebSocket] 负责连接与线程调度，解析规则集中在这里，二者分开之后
 * "字段解析是否正确"这件事才能被自动化测试真正验证到。
 *
 * 解析失败一律返回 [Result.Malformed] 而不是抛异常，也不用 0.0 之类的默认值
 * 蒙混过去——显示一个编造出来的 0 比显示"数据异常"更危险。
 */
object MessageParser {

    const val TYPE_DATA = "data"
    const val TYPE_ALARM_STATUS = "alarm_status"
    const val TYPE_STATISTICS = "statistics"
    const val TYPE_ASSISTANT = "assistant"

    sealed interface Result {
        data class Data(val value: RealtimeData) : Result
        data class Alarm(val value: AlarmStatus) : Result
        data class Stats(val value: Statistics) : Result
        data class Assistant(val value: AssistantAnswer) : Result
        /** 未知消息类型：不视为错误，旧版 App 应当能容忍服务端新增消息。 */
        data class Unknown(val type: String) : Result
        /** JSON 非法或必需字段缺失。 */
        data class Malformed(val reason: String) : Result
    }

    fun parse(text: String): Result {
        val json = try {
            JSONObject(text)
        } catch (e: JSONException) {
            return Result.Malformed(e.message ?: "invalid JSON")
        }

        return try {
            when (val type = json.optString("type")) {
                TYPE_DATA -> Result.Data(parseData(json))
                TYPE_ALARM_STATUS -> Result.Alarm(parseAlarm(json))
                TYPE_STATISTICS -> Result.Stats(parseStatistics(json))
                TYPE_ASSISTANT -> Result.Assistant(parseAssistant(json))
                else -> Result.Unknown(type)
            }
        } catch (e: JSONException) {
            Result.Malformed(e.message ?: "missing field")
        }
    }

    private fun parseData(json: JSONObject) = RealtimeData(
        deviceId = json.getString("device_id"),
        channel = json.getString("channel"),
        value = json.getDouble("value"),
        unit = json.optString("unit", ""),
        timestamp = if (json.isNull("timestamp")) null else json.optString("timestamp"),
        valid = json.optBoolean("valid", true),
    )

    private fun parseAlarm(json: JSONObject) = AlarmStatus(
        deviceId = json.getString("device_id"),
        channel = json.getString("channel"),
        value = json.getDouble("value"),
        unit = json.optString("unit", ""),
        threshold = json.getDouble("threshold"),
        kind = json.optString("kind", ""),
        triggered = json.getBoolean("triggered"),
    )

    private fun parseAssistant(json: JSONObject) = AssistantAnswer(
        text = json.getString("text"),
        // source 缺失时按"系统"处理而不是报错：它只影响气泡上的来源标签，
        // 而回答本身是有效的——为一个展示用字段丢掉整条答案不值得。
        source = json.optString("source", AssistantAnswer.SOURCE_TEMPLATE),
    )

    private fun parseStatistics(json: JSONObject) = Statistics(
        deviceId = json.getString("device_id"),
        channel = json.getString("channel"),
        unit = json.optString("unit", ""),
        current = json.getDouble("current"),
        minimum = json.getDouble("minimum"),
        maximum = json.getDouble("maximum"),
        average = json.getDouble("average"),
        sampleCount = json.getInt("sample_count"),
    )
}
