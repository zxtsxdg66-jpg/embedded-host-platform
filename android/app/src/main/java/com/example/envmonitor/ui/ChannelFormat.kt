package com.example.envmonitor.ui

import com.example.envmonitor.data.Channels
import java.util.Locale

/**
 * 数值的展示格式（纯展示层约定，不影响任何协议字段）。
 *
 * 小数位按通道分别决定，而不是统一一个格式：湿度传感器精度约 ±2%，
 * 显示 "58.0 %" 是虚假精度，显示 "58 %" 才诚实。
 *
 * 2026-09-18：温度与噪声由一位改为两位。起因是 PC 端历史表同日改成两位，
 * 于是同一条读数在手机上显示 25.0、在电脑上显示 25.03——"两边数不一样"
 * 是最容易让人不信任这套系统的那种不一致，哪怕它只是小数位。
 * **两端的小数位约定必须一起改**，PC 侧的对应文件是
 * src/ui/channel_display.py 的 CHANNEL_DECIMALS。
 *
 * 取整只发生在显示这一步：网关发来的、本机传给下一层的都还是原值。
 */
object ChannelFormat {

    private const val DEFAULT_DECIMALS = 2

    fun decimals(channel: String): Int = when (channel) {
        Channels.HUMIDITY -> 0
        else -> DEFAULT_DECIMALS
    }

    /** 按通道格式化。用 [Locale.US] 保证小数点是 "."，不随手机地区变成 ","。 */
    fun value(value: Double, channel: String): String =
        String.format(Locale.US, "%.${decimals(channel)}f", value)

    /**
     * 历史读数的时刻，只取时分秒。
     *
     * 服务端发的是带时区的 ISO-8601（如 `2026-09-17T04:00:00+00:00`）。
     * 这里**不做时区换算**：手机与 PC 在同一局域网、同一时区，而引入一个
     * 只在跨时区才有意义的转换，等于为一个不会发生的情况承担解析失败的风险。
     * 真要跨时区看数据时，该解决的是那件事本身，不是在这里补一层。
     *
     * 放在这里而不是 HistoryActivity 里，理由与 [StallDetector] 被抽出来时
     * 相同：Activity 里的函数在 JVM 单测中碰不到。
     */
    fun moment(timestamp: String?): String {
        if (timestamp.isNullOrBlank()) return PLACEHOLDER_TIME
        val timePart = timestamp.substringAfter('T', "")
        if (timePart.isEmpty()) return timestamp
        return timePart.take(8)
    }

    const val PLACEHOLDER_TIME = "--:--:--"
}
