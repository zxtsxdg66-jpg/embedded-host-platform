package com.example.envmonitor.data

import android.os.Handler
import android.os.Looper
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * PC 网关的 WebSocket 客户端，带自动重连。
 *
 * 覆盖 docs 要求的六种情况（不假设 WebSocket 永远稳定）：
 *  1. 连接成功       -> [Listener.onConnected]
 *  2. 连接失败       -> [Listener.onDisconnected] + 自动重连
 *  3. 断开           -> [Listener.onDisconnected] + 自动重连
 *  4. 重新连接       -> 指数退避（1s,2s,4s,8s... 上限 30s），避免 PC 没开时疯狂重试耗电
 *  5. 非法数据       -> JSON 解析失败时丢弃该条并回调 [Listener.onMalformedMessage]，
 *                      不中断连接（一条坏消息不该导致整条链路重连）
 *  6. 未知消息类型   -> 回调 [Listener.onUnknownMessage]，同样不中断连接
 *                      （PC 端将来新增消息类型时，旧版 App 应当继续正常工作）
 *
 * 所有回调都切到主线程，调用方可以直接更新 UI。
 */
class GatewayWebSocket(
    private val url: String,
    private val listener: Listener,
) {

    interface Listener {
        fun onConnected()
        fun onDisconnected(reason: String)
        fun onData(data: RealtimeData)
        fun onAlarmStatus(status: AlarmStatus)
        fun onStatistics(statistics: Statistics)

        /**
         * 迟到的问答答案（type: "assistant"）。
         *
         * 给了默认空实现，因为只有问答页关心它：首页照旧只处理数据、报警与统计，
         * 不必为了这个新增消息类型而改动已真机验证过的那条代码路径。
         */
        fun onAssistantAnswer(answer: AssistantAnswer) = Unit
        fun onMalformedMessage(raw: String, error: String)
        fun onUnknownMessage(type: String)
    }

    private val http = OkHttpClient.Builder()
        // 不设 readTimeout：WebSocket 是长连接，空闲期不应被当成超时断开。
        .readTimeout(0, TimeUnit.MILLISECONDS)
        // 心跳：OkHttp 会自动发 ping，帮助尽早发现"网络断了但 TCP 还没察觉"的假死连接。
        .pingInterval(20, TimeUnit.SECONDS)
        .build()

    private val mainHandler = Handler(Looper.getMainLooper())
    private val stopped = AtomicBoolean(false)
    private var webSocket: WebSocket? = null
    private var retryAttempt = 0

    fun connect() {
        stopped.set(false)
        openSocket()
    }

    /** 主动关闭，不再重连。 */
    fun close() {
        stopped.set(true)
        mainHandler.removeCallbacksAndMessages(null)
        webSocket?.close(NORMAL_CLOSURE, "client closed")
        webSocket = null
    }

    private fun openSocket() {
        if (stopped.get()) return
        val request = Request.Builder().url(url).build()
        webSocket = http.newWebSocket(request, SocketListener())
    }

    private fun scheduleReconnect(reason: String) {
        if (stopped.get()) return
        val delayMs = RECONNECT_BASE_DELAY_MS shl retryAttempt.coerceAtMost(MAX_BACKOFF_SHIFT)
        retryAttempt++
        post { listener.onDisconnected("$reason（${delayMs / 1000}s 后重连）") }
        mainHandler.postDelayed({ openSocket() }, delayMs)
    }

    private fun post(action: () -> Unit) = mainHandler.post(action)

    private inner class SocketListener : WebSocketListener() {

        override fun onOpen(webSocket: WebSocket, response: Response) {
            retryAttempt = 0
            post { listener.onConnected() }
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            // 解析规则集中在 MessageParser（纯 Kotlin，可在 JVM 单元测试中验证）；
            // 这里只负责把结果分发到主线程。情况 5（非法数据）与情况 6（未知类型）
            // 都只影响这一条消息，不会中断连接。
            when (val result = MessageParser.parse(text)) {
                is MessageParser.Result.Data -> post { listener.onData(result.value) }
                is MessageParser.Result.Alarm -> post { listener.onAlarmStatus(result.value) }
                is MessageParser.Result.Stats -> post { listener.onStatistics(result.value) }
                is MessageParser.Result.Assistant ->
                    post { listener.onAssistantAnswer(result.value) }
                is MessageParser.Result.Unknown -> post { listener.onUnknownMessage(result.type) }
                is MessageParser.Result.Malformed ->
                    post { listener.onMalformedMessage(text, result.reason) }
            }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            // 情况 2/3：连接失败或异常断开。
            scheduleReconnect(t.message ?: "连接失败")
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            if (!stopped.get()) {
                scheduleReconnect("服务端关闭连接")
            }
        }
    }

    private companion object {
        const val NORMAL_CLOSURE = 1000
        const val RECONNECT_BASE_DELAY_MS = 1000L
        const val MAX_BACKOFF_SHIFT = 5  // 1s << 5 = 32s，实际上限约 30s 量级
    }
}
