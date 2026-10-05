package com.example.envmonitor.ui

import com.example.envmonitor.data.Channels
import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.TimeZone

/**
 * ChannelFormat 的 JVM 单元测试。
 *
 * 2026-09-17 补：历史页把时刻与数值的格式化都交给了这里，而在此之前
 * 这个对象一直没有测试。两项都是纯函数、不碰任何 Android API，
 * 与 [com.example.envmonitor.data.StallDetector] 被抽出来时的理由相同。
 */
class ChannelFormatTest {

    // -- 数值：按通道定小数位 --------------------------------------------

    @Test
    fun `humidity shows no decimals because the sensor is not that precise`() {
        // 湿度传感器精度约 ±2%，显示 "58.0 %" 是虚假精度。
        assertEquals("58", ChannelFormat.value(58.0, Channels.HUMIDITY))
    }

    @Test
    fun `temperature keeps two decimals`() {
        // 2026-09-18 由一位改为两位，与 PC 端 channel_display.CHANNEL_DECIMALS
        // 保持一致——同一条读数两端显示不同，比多一位小数糟得多。
        assertEquals("25.53", ChannelFormat.value(25.53, Channels.TEMPERATURE))
    }

    @Test
    fun `noise keeps two decimals too`() {
        assertEquals("48.90", ChannelFormat.value(48.9, Channels.NOISE))
    }

    @Test
    fun `an unknown channel falls back to two decimals`() {
        assertEquals("1.00", ChannelFormat.value(1.0, "whatever"))
    }

    // -- 时刻：换成本地时间再取时分秒（2026-09-29 起）---------------------

    private val shanghai = TimeZone.getTimeZone("Asia/Shanghai")
    private val utc = TimeZone.getTimeZone("UTC")

    @Test
    fun `a UTC server timestamp is shown in local time`() {
        // 服务端真实发出的形状（带微秒、带 +00:00），取自 2026-09-17 的抓包。
        // 原先直接截出 07:17:27，比北京时间慢 8 小时。
        assertEquals(
            "15:17:27",
            ChannelFormat.moment("2026-09-17T07:17:27.778177+00:00", shanghai),
        )
    }

    @Test
    fun `handles a timestamp without microseconds`() {
        assertEquals("12:00:00", ChannelFormat.moment("2026-09-17T04:00:00+00:00", shanghai))
        assertEquals("04:00:00", ChannelFormat.moment("2026-09-17T04:00:00+00:00", utc))
    }

    @Test
    fun `an offset that is not UTC is honoured`() {
        assertEquals("04:00:00", ChannelFormat.moment("2026-09-17T12:00:00+08:00", utc))
    }

    @Test
    fun `an unparseable time falls back to cutting out the clock part`() {
        assertEquals("25:61:99", ChannelFormat.moment("2026-09-17T25:61:99.5", shanghai))
    }

    @Test
    fun `a missing timestamp shows a placeholder rather than an empty cell`() {
        // 空白单元格看起来像"这一行坏了"，占位符看起来像"这一项没有"。
        assertEquals(ChannelFormat.PLACEHOLDER_TIME, ChannelFormat.moment(null))
        assertEquals(ChannelFormat.PLACEHOLDER_TIME, ChannelFormat.moment(""))
    }

    @Test
    fun `text without a T separator is passed through unchanged`() {
        // 服务端不会这样发；万一发了，原样显示比截出一段没有意义的字符好——
        // 至少能看出"收到的东西不对"。
        assertEquals("unexpected", ChannelFormat.moment("unexpected"))
    }
}
