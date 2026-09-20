package com.example.envmonitor.ui

import androidx.annotation.ColorRes
import androidx.annotation.StringRes
import com.example.envmonitor.R

/**
 * 界面上的连接状态（六态）。
 *
 * **完全由已有回调派生，不改动 `data/GatewayWebSocket.kt` 一行**：
 *
 * | 状态            | 由什么派生                                        |
 * | --------------- | ------------------------------------------------ |
 * | [DISCONNECTED]  | 初始态 / 用户主动断开                             |
 * | [CONNECTING]    | 发起连接 -> `/health` 返回前                      |
 * | [ONLINE]        | `onConnected()` 之后，且 10 秒内有数据            |
 * | [STALLED]       | `onConnected()` 之后，但超过 10 秒没有新数据      |
 * | [RECONNECTING]  | `onDisconnected()` 之后，连续失败次数 < 3         |
 * | [ERROR]         | `/health` 失败，或连续失败 >= 3 次                |
 *
 * [STALLED] 是这里最有价值的一态：WebSocket 假死（TCP 没断但服务端不再推送）时，
 * 旧界面看起来一切正常，用户无从察觉；现在会明确降级提示。
 */
enum class ConnectionUiState(
    @StringRes val labelRes: Int,
    @ColorRes val colorRes: Int,
) {
    DISCONNECTED(R.string.conn_disconnected, R.color.state_idle),
    CONNECTING(R.string.conn_connecting, R.color.state_warn),
    ONLINE(R.string.conn_online, R.color.accent),
    STALLED(R.string.conn_stalled, R.color.state_warn),
    RECONNECTING(R.string.conn_reconnecting, R.color.state_warn),
    ERROR(R.string.conn_error, R.color.state_alarm),
    ;

    /** 数值是否应被视为"当前有效"。非在线状态下指标卡会降透明度提示这是旧值。 */
    val isLive: Boolean get() = this == ONLINE
}
