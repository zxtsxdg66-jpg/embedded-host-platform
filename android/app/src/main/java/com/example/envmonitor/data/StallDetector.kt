package com.example.envmonitor.data

/**
 * 判断实时数据是否已经停滞。
 *
 * 解决的是一个界面看不出来的故障：WebSocket **假死**——TCP 连接没断、
 * `onDisconnected()` 不会触发、重连逻辑因此永远不启动，而服务端已经不再推送。
 * 旧界面在这种情况下看起来一切正常，读数停在最后一个值上，用户无从察觉。
 *
 * 这段判断原先内联在 `MainActivity.onTick()` 里。2026-09-09 抽出来，
 * 唯一目的是**让它可测**：容错机制本身早已实现，但一直没有任何用例证明它成立，
 * 而它依赖 `SystemClock` 与 Activity 生命周期，留在原地就只能靠人工制造假死来验。
 * 抽成不含任何 Android 依赖的纯函数之后，普通 JVM 单测就能覆盖边界。
 */
object StallDetector {

    /**
     * 多久没有新数据算停滞。
     *
     * 采集周期是 3 秒，取 10 秒约等于"连丢三帧"。取值偏宽是有意的：
     * 误报会让界面在正常波动时反复降级，比晚几秒发现假死更烦人。
     */
    const val DEFAULT_THRESHOLD_MS = 10_000L

    /**
     * @param isOnline    仅在线状态才判停滞。离线/重连中另有各自的提示，
     *                    在那些状态上再叠一个"停滞"只会让措辞互相打架。
     * @param lastDataAt  最后一次收到数据的时刻，从未收到过则为 0。
     * @param connectedAt 连接建立的时刻。**参与比较**是必要的：刚连上还没
     *                    收到第一帧时 `lastDataAt` 仍是 0，只看它会让每次连接
     *                    在第一秒就被判成停滞。
     * @param now         当前时刻，与上面两个同源（调用方传 elapsedRealtime）。
     */
    fun isStalled(
        isOnline: Boolean,
        lastDataAt: Long,
        connectedAt: Long,
        now: Long,
        thresholdMs: Long = DEFAULT_THRESHOLD_MS,
    ): Boolean {
        if (!isOnline) return false
        val reference = maxOf(lastDataAt, connectedAt)
        // 两者都为 0：还没连过，无从判断。
        if (reference <= 0L) return false
        return now - reference > thresholdMs
    }
}
