package com.example.envmonitor.data

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * PC 网关的 REST 客户端（第一阶段只用到查询类接口）。
 *
 * 所有方法都是**阻塞式**的，必须在后台线程调用（MainActivity 用协程的 IO 调度器
 * 调用它们）——刻意不在这一层内部起线程，让调用方对线程有完全的控制权。
 *
 * 返回 [Result] 而不是抛异常：网络失败在真机环境里是常态（PC 没开、IP 填错、
 * 不在同一局域网、防火墙拦截），调用方需要把失败原因显示给用户，而不是崩溃。
 */
class GatewayClient(private val baseUrl: String) {

    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .build()

    /** GET /devices -> 设备 id 列表 */
    fun listDevices(): Result<List<String>> = get("/devices").mapCatching { body ->
        val array = JSONObject(body).getJSONArray("devices")
        (0 until array.length()).map { array.getString(it) }
    }

    /** GET /devices/{id}/status -> 设备状态 */
    fun deviceStatus(deviceId: String): Result<DeviceStatus> =
        get("/devices/$deviceId/status").mapCatching { body ->
            val json = JSONObject(body)
            DeviceStatus(
                deviceId = json.getString("device_id"),
                isConnected = json.getBoolean("is_connected"),
                isOccupied = json.getBoolean("is_occupied"),
                // occupant 可能是 JSON null，getString 会把它读成字符串 "null"，
                // 所以必须显式判空
                occupant = if (json.isNull("occupant")) null else json.getString("occupant"),
            )
        }

    /**
     * POST /assistant/ask -> 即时答案（规则 + 模板，毫秒级）。
     *
     * 这个请求**不等模型**。PC 端若接了本地模型，改写后的或"模型读懂了规则没认出的
     * 问句"那条答案会在数秒后经 WebSocket 补送（type: "assistant"），
     * 由问答页替换掉这里返回的这条。只调本接口也能得到正确答案，只是看不到改进后的。
     *
     * 读超时单独放宽到 10 秒：本调用虽然不等模型，但 PC 端仍要走一遍取数与模板渲染，
     * 而默认的 5 秒是按"查设备列表"这类纯查询定的。
     */
    fun ask(question: String): Result<AssistantAnswer> = runCatching {
        val payload = JSONObject().put("question", question).toString()
        val request = Request.Builder()
            .url("$baseUrl/assistant/ask")
            .post(payload.toRequestBody(JSON_MEDIA_TYPE))
            .build()
        askHttp.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw IllegalStateException("HTTP ${response.code}: $body")
            }
            val json = JSONObject(body)
            AssistantAnswer(
                text = json.getString("text"),
                source = json.optString("source", AssistantAnswer.SOURCE_TEMPLATE),
            )
        }
    }

    /**
     * GET /devices/{id}/channels/{channel}/history -> 该通道已存的读数。
     *
     * 读的是 **PC 本地历史库**，不是云端——手机不持有任何云端凭证，
     * 也不直连对象存储（见 docs/decisions/06-history.md）。
     *
     * [limit] 默认 200 而不是服务端的 500：这一页把结果一条条加进
     * LinearLayout（与问答页同样不引入 RecyclerView，理由见 app/build.gradle.kts
     * 里"依赖越少越好"那段注释），条数太多会让页面打开时明显卡顿。
     * 需要更长的跨度时由调用方显式加大。
     */
    fun queryHistory(
        deviceId: String,
        channel: String,
        limit: Int = 200,
    ): Result<HistoryPage> =
        get("/devices/$deviceId/channels/$channel/history?limit=$limit")
            .mapCatching { body -> HistoryParser.parse(body) }

    /** GET /health -> 用于"PC 是否可达"的连通性探测 */
    fun health(): Result<String> = get("/health").mapCatching { body ->
        JSONObject(body).optString("mode", "unknown")
    }

    private val askHttp = http.newBuilder()
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    private fun get(path: String): Result<String> = runCatching {
        val request = Request.Builder().url("$baseUrl$path").get().build()
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw IllegalStateException("HTTP ${response.code}: $body")
            }
            body
        }
    }

    private companion object {
        val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    }
}
