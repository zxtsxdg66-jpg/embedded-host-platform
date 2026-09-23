package com.example.envmonitor.data

import org.json.JSONException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * HistoryParser 的 JVM 单元测试（不需要模拟器/真机）。
 *
 * 与 [MessageParserTest] 同一条规矩：下面 REAL_* 两条响应不是手写编造的，
 * 而是 2026-09-17 从**真实运行的 PC 网关**（`gateway.server` 的历史端点，
 * 经 FastAPI TestClient 实跑）原样抓下来的。因此这些用例验证的是
 * "Android 端能否解析 PC 端真实发出的数据"，而不是"能否解析我以为它会发的数据"。
 *
 * 覆盖面按 `docs/02_Architecture/History_And_Cloud_Design.md` 第 7 节的要求：
 * 正常、空列表、字段缺失、请求失败各一条。
 */
class HistoryParserTest {

    private companion object {
        /** 真实抓包：两条温度读数，limit=2。 */
        const val REAL_HISTORY = """{"device_id":"sim-temp","channel":"temperature",""" +
            """"unit":"°C","points":[""" +
            """{"value":36.28365565119134,"timestamp":"2026-09-17T07:17:27.778177+00:00","valid":true},""" +
            """{"value":36.43629516413204,"timestamp":"2026-09-17T07:17:27.777919+00:00","valid":true}]}"""

        /** 真实抓包：问一条不存在的通道。空不是错误，是正常答案。 */
        const val REAL_EMPTY =
            """{"device_id":"sim-temp","channel":"nope","unit":"","points":[]}"""
    }

    // -- 正常响应（真实抓包） -------------------------------------------

    @Test
    fun `parses a real history response from the gateway`() {
        val page = HistoryParser.parse(REAL_HISTORY)

        assertEquals("sim-temp", page.deviceId)
        assertEquals("temperature", page.channel)
        assertEquals("°C", page.unit)
        assertEquals(2, page.points.size)
    }

    @Test
    fun `keeps the order the server sent`() {
        // 服务端按"新的在前"返回，解析不得重排——页面直接照这个顺序显示。
        val page = HistoryParser.parse(REAL_HISTORY)

        assertEquals(36.28365565119134, page.points[0].value, 1e-9)
        assertEquals(36.43629516413204, page.points[1].value, 1e-9)
    }

    @Test
    fun `keeps the timestamp text as the server wrote it`() {
        // 不在手机上解析成时间对象：时刻的权威解释在 PC 端，这里只负责显示。
        val page = HistoryParser.parse(REAL_HISTORY)

        assertEquals("2026-09-17T07:17:27.778177+00:00", page.points[0].timestamp)
    }

    // -- 空列表 ----------------------------------------------------------

    @Test
    fun `an empty points array is a normal answer not an error`() {
        val page = HistoryParser.parse(REAL_EMPTY)

        assertTrue(page.points.isEmpty())
        assertEquals("nope", page.channel)
        // 未知通道没有单位，服务端发空串；不能因此把整条响应判成异常。
        assertEquals("", page.unit)
    }

    // -- 字段缺失 --------------------------------------------------------

    @Test(expected = JSONException::class)
    fun `a reading without a value is rejected rather than defaulted`() {
        // 用 0.0 顶替一条读不出来的读数比报错危险得多：界面会把编造的 0
        // 当成真实读数画出来。与 MessageParser 对 data 消息的处理一致。
        val json = """{"device_id":"d","channel":"temperature","unit":"°C",""" +
            """"points":[{"timestamp":"2026-09-17T07:17:27+00:00","valid":true}]}"""

        HistoryParser.parse(json)
    }

    @Test(expected = JSONException::class)
    fun `a response without the points array is rejected`() {
        HistoryParser.parse("""{"device_id":"d","channel":"temperature","unit":"°C"}""")
    }

    @Test
    fun `a null timestamp becomes null not the string null`() {
        // optString 会把 JSON null 读成字符串 "null"，必须显式判空——
        // 与 GatewayClient 解析 deviceStatus 的 occupant 是同一个坑。
        val json = """{"device_id":"d","channel":"temperature","unit":"°C",""" +
            """"points":[{"value":25.5,"timestamp":null,"valid":true}]}"""

        val page = HistoryParser.parse(json)

        assertNull(page.points[0].timestamp)
    }

    @Test
    fun `an invalid reading is kept rather than dropped`() {
        // 无效读数是链路质量的证据，PC 端照存不删（设计文档 4.1 节），
        // 客户端同样不能在解析时把它过滤掉。
        val json = """{"device_id":"d","channel":"noise","unit":"dB",""" +
            """"points":[{"value":0.0,"timestamp":null,"valid":false}]}"""

        val page = HistoryParser.parse(json)

        assertEquals(1, page.points.size)
        assertEquals(false, page.points[0].valid)
    }

    @Test
    fun `valid defaults to true when the server omits it`() {
        val json = """{"device_id":"d","channel":"temperature","unit":"°C",""" +
            """"points":[{"value":25.5,"timestamp":null}]}"""

        assertTrue(HistoryParser.parse(json).points[0].valid)
    }

    // -- 请求失败 --------------------------------------------------------

    @Test(expected = JSONException::class)
    fun `an error page instead of json is rejected`() {
        // GatewayClient 在 HTTP 非 2xx 时抛 IllegalStateException，由 runCatching
        // 兜成 Result.failure，那一层不经过本解析器。这里守的是另一种失败：
        // 状态码是 200 但正文不是 JSON（例如中间有代理返回了一张错误页）。
        // 那种情况必须报错，不能解析出一个空页面让用户以为"没有历史"。
        HistoryParser.parse("<html><body>502 Bad Gateway</body></html>")
    }

    @Test(expected = JSONException::class)
    fun `an empty body is rejected`() {
        HistoryParser.parse("")
    }
}
