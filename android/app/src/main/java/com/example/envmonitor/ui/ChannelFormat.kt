package com.example.envmonitor.ui

import com.example.envmonitor.data.Channels
import java.text.ParseException
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

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
     * 历史读数的时刻，换成手机本地时间后取时分秒。
     *
     * 服务端发的是带时区的 ISO-8601，一律 UTC（如 `2026-09-17T04:00:00+00:00`）。
     *
     * 2026-09-29 改：原先**不做时区换算**、直接截出时分秒，理由是"手机与 PC 在同一时区"。
     * 但时区相同并不等于时间串是本地时间——服务端发的是 UTC，于是北京时间 14:05 的读数
     * 在历史页上显示成 06:05，差了整整 8 小时（截图核对时发现）。现在按串里的偏移解析，
     * 再按 [zone]（默认手机本地时区）输出。
     *
     * 用 [SimpleDateFormat] 而不是 java.time：minSdk 24 还没有 java.time。
     * 它不认变长的小数秒，所以先把 `.778177` 这一段去掉——显示只到秒，去掉不损失什么。
     * 解析失败时退回原来的做法（截出时分秒），宁可显示 UTC，也不显示一格空白。
     *
     * 放在这里而不是 HistoryActivity 里，理由与 [StallDetector] 被抽出来时
     * 相同：Activity 里的函数在 JVM 单测中碰不到。
     */
    fun moment(timestamp: String?, zone: TimeZone = TimeZone.getDefault()): String {
        if (timestamp.isNullOrBlank()) return PLACEHOLDER_TIME
        val timePart = timestamp.substringAfter('T', "")
        if (timePart.isEmpty()) return timestamp
        val withoutFraction = timestamp.replace(FRACTION, "")
        return try {
            val parser = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US)
            val instant = parser.parse(withoutFraction) ?: return timePart.take(8)
            val printer = SimpleDateFormat("HH:mm:ss", Locale.US)
            printer.timeZone = zone
            printer.format(instant)
        } catch (e: ParseException) {
            timePart.take(8)
        } catch (e: IllegalArgumentException) {
            timePart.take(8)
        }
    }

    private val FRACTION = Regex("""\.\d+(?=[+-]\d{2}:\d{2}$|Z$)""")

    const val PLACEHOLDER_TIME = "--:--:--"
}
