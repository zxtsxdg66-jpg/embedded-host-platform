package com.example.envmonitor.data

import org.json.JSONException
import org.json.JSONObject

/**
 * 把 `GET /devices/{id}/channels/{channel}/history` 的响应解析成 [HistoryPage]。
 *
 * 与 [MessageParser] 同一取向：做成**不依赖任何 Android API** 的纯 Kotlin 对象
 * （只用 org.json），这样它能在普通 JVM 单元测试里直接跑。解析逻辑留在
 * [GatewayClient] 里是跑不了测试的——那个类依赖 OkHttp。
 *
 * 与 [MessageParser] 的一处不同：这里**用异常而不是 sealed Result**。
 * 那边解析的是 WebSocket 推来的消息流，一条坏消息不该中断整条连接，所以要有
 * `Malformed` 这个可继续处理的返回值；这里是一次性的请求-响应，调用方本就用
 * `Result` 包着，抛出去由 `runCatching` 接住即可，再套一层反而多一次拆包。
 */
object HistoryParser {

    /**
     * @throws JSONException 响应不是合法 JSON，或缺少必需字段。
     *
     * 必需与可选的划分与 [MessageParser] 一致：**数值不能有默认值**
     * （用 0.0 顶替一条读不出来的读数，比报错危险得多——界面会把编造的 0
     * 当成真实读数画出来）；单位、有效标志这类只影响展示的字段才允许缺省。
     */
    fun parse(body: String): HistoryPage {
        val json = JSONObject(body)
        val array = json.getJSONArray("points")
        return HistoryPage(
            deviceId = json.getString("device_id"),
            channel = json.getString("channel"),
            unit = json.optString("unit", ""),
            points = (0 until array.length()).map { index ->
                val point = array.getJSONObject(index)
                HistoryPoint(
                    value = point.getDouble("value"),
                    // 服务端在时间戳缺失时发 JSON null；optString 会把它读成
                    // 字符串 "null"，所以必须显式判空——与 GatewayClient
                    // 解析 deviceStatus 的 occupant 是同一个坑。
                    timestamp = if (point.isNull("timestamp")) {
                        null
                    } else {
                        point.optString("timestamp")
                    },
                    valid = point.optBoolean("valid", true),
                )
            },
        )
    }
}
