package com.example.envmonitor.data

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 静默失连（WebSocket 假死）检测。
 *
 * 第 10 章把这项列为"容错机制已实现但未专门测试"——机制一直在
 * `MainActivity.onTick()` 里，只是没有任何用例证明它成立。2026-09-09 把判定
 * 抽成 [StallDetector] 之后补上本组用例，那条不足就此闭环。
 *
 * 时间一律用显式毫秒数传入，不碰 `SystemClock`：判定本身与 Android 无关，
 * 让它保持无关才能用普通 JVM 单测覆盖边界。
 */
class StallDetectorTest {

    private val threshold = StallDetector.DEFAULT_THRESHOLD_MS

    @Test
    fun `no data for longer than the threshold is a stall`() {
        assertTrue(
            StallDetector.isStalled(
                isOnline = true,
                lastDataAt = 1_000L,
                connectedAt = 500L,
                now = 1_000L + threshold + 1,
            ),
        )
    }

    @Test
    fun `data within the threshold is not a stall`() {
        assertFalse(
            StallDetector.isStalled(
                isOnline = true,
                lastDataAt = 1_000L,
                connectedAt = 500L,
                now = 1_000L + threshold - 1,
            ),
        )
    }

    @Test
    fun `exactly at the threshold is not yet a stall`() {
        // 判定用严格大于：边界上再等一个 tick，宁可晚一秒也不误报。
        assertFalse(
            StallDetector.isStalled(
                isOnline = true,
                lastDataAt = 1_000L,
                connectedAt = 500L,
                now = 1_000L + threshold,
            ),
        )
    }

    @Test
    fun `a fresh connection with no data yet is not a stall`() {
        // 这条是 connectedAt 参与比较的理由：刚连上还没收到第一帧时
        // lastDataAt 仍是 0，只看它会让每次连接在第一秒就被判成停滞。
        assertFalse(
            StallDetector.isStalled(
                isOnline = true,
                lastDataAt = 0L,
                connectedAt = 10_000L,
                now = 10_000L + threshold - 1,
            ),
        )
    }

    @Test
    fun `a connection that never delivered anything does stall eventually`() {
        // 连上了却一帧都没来，同样是假死——只是参照点变成连接时刻。
        assertTrue(
            StallDetector.isStalled(
                isOnline = true,
                lastDataAt = 0L,
                connectedAt = 10_000L,
                now = 10_000L + threshold + 1,
            ),
        )
    }

    @Test
    fun `never connected is not a stall`() {
        assertFalse(
            StallDetector.isStalled(
                isOnline = true,
                lastDataAt = 0L,
                connectedAt = 0L,
                now = 999_999L,
            ),
        )
    }

    @Test
    fun `offline states are never reported as stalled`() {
        // 离线与重连中各有自己的提示，再叠一个"停滞"只会让措辞互相打架。
        assertFalse(
            StallDetector.isStalled(
                isOnline = false,
                lastDataAt = 1_000L,
                connectedAt = 500L,
                now = 1_000L + threshold * 10,
            ),
        )
    }

    @Test
    fun `the newer of the two reference points wins`() {
        // 重连之后 connectedAt 比旧的 lastDataAt 新，应以它为准，
        // 否则一次重连会立刻被判成停滞。
        assertFalse(
            StallDetector.isStalled(
                isOnline = true,
                lastDataAt = 1_000L,
                connectedAt = 60_000L,
                now = 60_000L + threshold - 1,
            ),
        )
    }

    @Test
    fun `the threshold is about three missed reporting cycles`() {
        // 采集周期 3 秒；10 秒约等于连丢三帧。取值偏宽是有意的：
        // 误报会让界面在正常波动时反复降级，比晚几秒发现假死更烦人。
        assertTrue(StallDetector.DEFAULT_THRESHOLD_MS >= 9_000L)
        assertTrue(StallDetector.DEFAULT_THRESHOLD_MS <= 15_000L)
    }
}
