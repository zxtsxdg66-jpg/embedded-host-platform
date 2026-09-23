package com.example.envmonitor.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * MessageParser 的 JVM 单元测试（不需要模拟器/真机）。
 *
 * 下面 REAL_* 三条报文不是手写编造的，而是 2026-08-15 从**真实运行的 PC 网关**
 * （`python scripts/run_api_server.py`）的 WebSocket 上原样抓取下来的，因此这些
 * 测试验证的是"Android 端能否解析 PC 端真实发出的数据"，而不是"能否解析我以为
 * PC 会发出的数据"。
 */
class MessageParserTest {

    private companion object {
        const val REAL_DATA = """{"type":"data","device_id":"sim-env-1-temp",""" +
            """"channel":"temperature","value":28.890665880490687,"unit":"°C",""" +
            """"timestamp":"2026-08-15T11:37:14.400858+00:00","valid":true}"""

        const val REAL_ALARM = """{"type":"alarm_status","device_id":"sim-env-1-temp",""" +
            """"channel":"temperature","value":28.890665880490687,"unit":"°C",""" +
            """"threshold":35.0,"kind":"ABOVE_MAX","triggered":false}"""

        const val REAL_STATISTICS = """{"type":"statistics","device_id":"sim-env-1-temp",""" +
            """"channel":"temperature","unit":"°C","current":28.890665880490687,""" +
            """"minimum":28.648886725581363,"maximum":29.427164340731505,""" +
            """"average":29.095995137529204,"sample_count":53}"""
    }

    // -- 正常报文（真实抓包） -------------------------------------------

    @Test
    fun `parses real data message from gateway`() {
        val result = MessageParser.parse(REAL_DATA)

        assertTrue(result is MessageParser.Result.Data)
        val data = (result as MessageParser.Result.Data).value
        assertEquals("sim-env-1-temp", data.deviceId)
        assertEquals("temperature", data.channel)
        assertEquals(28.890665880490687, data.value, 1e-9)
        assertEquals("°C", data.unit)
        assertEquals("2026-08-15T11:37:14.400858+00:00", data.timestamp)
        assertTrue(data.valid)
    }

    @Test
    fun `parses real alarm_status message from gateway`() {
        val result = MessageParser.parse(REAL_ALARM)

        assertTrue(result is MessageParser.Result.Alarm)
        val alarm = (result as MessageParser.Result.Alarm).value
        assertEquals("temperature", alarm.channel)
        assertEquals(35.0, alarm.threshold, 1e-9)
        assertEquals("ABOVE_MAX", alarm.kind)
        // triggered=false 必须被正确解析：这是客户端得知"已恢复正常"的唯一依据
        assertEquals(false, alarm.triggered)
    }

    @Test
    fun `parses real statistics message from gateway`() {
        val result = MessageParser.parse(REAL_STATISTICS)

        assertTrue(result is MessageParser.Result.Stats)
        val stats = (result as MessageParser.Result.Stats).value
        assertEquals(28.890665880490687, stats.current, 1e-9)
        assertEquals(28.648886725581363, stats.minimum, 1e-9)
        assertEquals(29.427164340731505, stats.maximum, 1e-9)
        assertEquals(29.095995137529204, stats.average, 1e-9)
        assertEquals(53, stats.sampleCount)
    }

    // -- 三个通道的单位都能正确解析 --------------------------------------

    @Test
    fun `parses units for all three channels`() {
        val cases = mapOf("temperature" to "°C", "humidity" to "%", "noise" to "dB")

        cases.forEach { (channel, unit) ->
            val json = """{"type":"data","device_id":"d","channel":"$channel",""" +
                """"value":1.0,"unit":"$unit","timestamp":null,"valid":true}"""

            val result = MessageParser.parse(json)

            assertTrue(result is MessageParser.Result.Data)
            assertEquals(unit, (result as MessageParser.Result.Data).value.unit)
        }
    }

    @Test
    fun `null timestamp becomes null not the string null`() {
        val json = """{"type":"data","device_id":"d","channel":"noise","value":1.0,""" +
            """"unit":"dB","timestamp":null,"valid":true}"""

        val result = MessageParser.parse(json)

        assertNull((result as MessageParser.Result.Data).value.timestamp)
    }

    // -- 异常情况（用户要求覆盖的第 5、6 两种） ---------------------------

    @Test
    fun `malformed json is reported not thrown`() {
        val result = MessageParser.parse("{this is not json")

        assertTrue(result is MessageParser.Result.Malformed)
    }

    @Test
    fun `empty string is reported as malformed`() {
        assertTrue(MessageParser.parse("") is MessageParser.Result.Malformed)
    }

    @Test
    fun `missing required field is reported as malformed`() {
        // 缺 value 字段：不能用 0.0 顶替，必须报为异常数据
        val json = """{"type":"data","device_id":"d","channel":"noise","unit":"dB"}"""

        assertTrue(MessageParser.parse(json) is MessageParser.Result.Malformed)
    }

    @Test
    fun `unknown message type is reported as unknown not malformed`() {
        // 服务端将来新增消息类型时，旧版 App 必须能容忍并继续工作
        val json = """{"type":"some_future_type","foo":1}"""

        val result = MessageParser.parse(json)

        assertTrue(result is MessageParser.Result.Unknown)
        assertEquals("some_future_type", (result as MessageParser.Result.Unknown).type)
    }

    @Test
    fun `message without type field is reported as unknown`() {
        val result = MessageParser.parse("""{"device_id":"d"}""")

        assertTrue(result is MessageParser.Result.Unknown)
    }

    @Test
    fun `assistant answer is parsed with its source`() {
        val json = """{"type":"assistant","text":"噪声现在是 40.5dB。","source":"model"}"""

        val result = MessageParser.parse(json)

        assertTrue(result is MessageParser.Result.Assistant)
        val answer = (result as MessageParser.Result.Assistant).value
        assertEquals("噪声现在是 40.5dB。", answer.text)
        assertEquals(AssistantAnswer.SOURCE_MODEL, answer.source)
    }

    @Test
    fun `assistant answer without source falls back to template`() {
        // source 只影响气泡上的来源标签；为一个展示字段丢掉整条真实答案不值得
        val json = """{"type":"assistant","text":"温度现在是 20.8℃。"}"""

        val result = MessageParser.parse(json)

        assertTrue(result is MessageParser.Result.Assistant)
        assertEquals(
            AssistantAnswer.SOURCE_TEMPLATE,
            (result as MessageParser.Result.Assistant).value.source,
        )
    }

    @Test
    fun `assistant answer without text is malformed`() {
        // 没有正文就没有可显示的内容，不能拿空串冒充一条回答
        val json = """{"type":"assistant","source":"model"}"""

        assertTrue(MessageParser.parse(json) is MessageParser.Result.Malformed)
    }
}
