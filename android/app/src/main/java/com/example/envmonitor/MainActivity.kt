package com.example.envmonitor

import android.content.Intent
import android.content.res.ColorStateList
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.example.envmonitor.data.AlarmStatus
import com.example.envmonitor.data.Channels
import com.example.envmonitor.data.DeviceStatus
import com.example.envmonitor.data.GatewayClient
import com.example.envmonitor.data.GatewayWebSocket
import com.example.envmonitor.data.RealtimeData
import com.example.envmonitor.data.StallDetector
import com.example.envmonitor.data.Statistics
import com.example.envmonitor.databinding.ActivityMainBinding
import com.example.envmonitor.databinding.ItemDeviceBinding
import com.example.envmonitor.ui.ChannelFormat
import com.example.envmonitor.ui.ConnectionUiState
import com.example.envmonitor.ui.MetricCardView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 环境监测首页。
 *
 * 第二阶段只重写了**呈现**部分；连接流程（/health 探测 -> /devices ->
 * 逐台 /devices/{id}/status -> 建 WebSocket）的顺序、线程调度与 `data/` 下四个
 * 文件全部保持第一阶段真机验证通过的原样。地址输入已迁到 [SettingsActivity]，
 * 因此这里改为直接从 [ServerConfig] 读取。
 *
 * 界面状态机见 [ConnectionUiState]：六种状态全部由 [GatewayWebSocket.Listener]
 * 已有的回调加一个 1 秒 tick 派生，没有向网络层要任何新能力。
 */
class MainActivity : AppCompatActivity(), GatewayWebSocket.Listener {

    private lateinit var binding: ActivityMainBinding
    private lateinit var cards: Map<String, MetricCardView>

    private var webSocket: GatewayWebSocket? = null
    private val timeFormat = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
    private val logLines = ArrayDeque<String>()
    private var logExpanded = false

    private val ticker = Handler(Looper.getMainLooper())
    private val tickerTask = object : Runnable {
        override fun run() {
            onTick()
            ticker.postDelayed(this, TICK_INTERVAL_MS)
        }
    }

    private var state = ConnectionUiState.DISCONNECTED
    /** 当前这条连接用的是哪个地址；从设置页返回时用它判断要不要重连。 */
    private var connectedBaseUrl: String? = null

    /**
     * 最近一次拿到的第一台设备 id，进历史页时带过去。
     *
     * 这一版只看第一台：模拟模式下三台设备各只带一条通道，硬件模式下只有一台，
     * 无论哪种，"看哪台的历史"都还不构成一个需要用户回答的问题。真要多台可选时，
     * 该做的是一个设备选择器，而不是在这里猜。
     */
    private var primaryDeviceId: String? = null
    private var lastDataAt = 0L
    private var connectedAt = 0L
    private var receivedCount = 0
    private var failureCount = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        cards = mapOf(
            Channels.TEMPERATURE to binding.cardTemperature,
            Channels.HUMIDITY to binding.cardHumidity,
            Channels.NOISE to binding.cardNoise,
        )
        binding.cardTemperature.setup(Channels.TEMPERATURE, getString(R.string.label_temperature))
        binding.cardHumidity.setup(Channels.HUMIDITY, getString(R.string.label_humidity))
        binding.cardNoise.setup(Channels.NOISE, getString(R.string.label_noise))

        binding.textSubtitle.text =
            getString(R.string.home_subtitle_loading, getString(R.string.site_name))

        binding.buttonSettings.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }
        // 问答独立成页：首页第一眼应当是环境数据，而不是输入框——与设置页同样的理由。
        binding.buttonHistory.setOnClickListener {
            startActivity(
                Intent(this, HistoryActivity::class.java).putExtra(
                    HistoryActivity.EXTRA_DEVICE_ID, primaryDeviceId
                )
            )
        }
        binding.buttonAssistant.setOnClickListener {
            startActivity(Intent(this, AssistantActivity::class.java))
        }
        binding.buttonReconnect.setOnClickListener { reconnect() }
        binding.logHeader.setOnClickListener { toggleLog() }

        applyState(ConnectionUiState.DISCONNECTED)
        renderLog()
        connect()
    }

    override fun onResume() {
        super.onResume()
        ticker.postDelayed(tickerTask, TICK_INTERVAL_MS)
        // 从设置页回来：地址变了才重连，没变就不打断已有连接
        val configured = ServerConfig.httpBaseUrl(this)
        if (connectedBaseUrl != null && connectedBaseUrl != configured) {
            appendLog(getString(R.string.log_address_changed))
            reconnect()
        }
    }

    override fun onPause() {
        ticker.removeCallbacks(tickerTask)
        super.onPause()
    }

    override fun onDestroy() {
        super.onDestroy()
        ticker.removeCallbacksAndMessages(null)
        webSocket?.close()
        webSocket = null
    }

    // -- 连接 / 断开 ----------------------------------------------------

    private fun reconnect() {
        webSocket?.close()
        webSocket = null
        connect()
    }

    /**
     * 连接流程与第一阶段完全一致，只是地址来源从输入框换成了 [ServerConfig]，
     * 以及把结果渲染到新的卡片式界面上。
     */
    private fun connect() {
        val baseUrl = ServerConfig.httpBaseUrl(this)
        connectedBaseUrl = baseUrl
        failureCount = 0
        receivedCount = 0
        lastDataAt = 0L
        applyState(ConnectionUiState.CONNECTING)
        showDeviceHint(getString(R.string.device_loading))
        appendLog(getString(R.string.log_connecting, baseUrl))

        lifecycleScope.launch {
            val client = GatewayClient(baseUrl)

            // 1) 先用 /health 做连通性探测：能区分"PC 没开/IP 错"与"WebSocket 有问题"
            val health = withContext(Dispatchers.IO) { client.health() }
            health.onFailure { error ->
                applyState(ConnectionUiState.ERROR)
                appendLog(getString(R.string.log_health_failed, error.message.orEmpty()))
                showDeviceHint(getString(R.string.device_failed))
                return@launch
            }
            val mode = health.getOrNull()
            appendLog(getString(R.string.log_health_ok, mode.orEmpty()))
            // 明确提示数据来源，避免把模拟数据误认为真实 STM32 数据
            binding.bannerSimulated.visibility =
                if (mode == MODE_SIMULATOR) View.VISIBLE else View.GONE

            // 2) 设备列表 + 每台设备状态
            val devices = withContext(Dispatchers.IO) { client.listDevices() }
            devices.onSuccess { ids ->
                if (ids.isEmpty()) {
                    showDeviceHint(getString(R.string.device_empty))
                } else {
                    val statuses = withContext(Dispatchers.IO) {
                        ids.map { id -> id to client.deviceStatus(id).getOrNull() }
                    }
                    renderDevices(statuses)
                }
            }.onFailure {
                showDeviceHint(getString(R.string.device_failed))
            }

            // 3) 建 WebSocket，开始接收实时数据
            webSocket = GatewayWebSocket(
                ServerConfig.webSocketUrl(this@MainActivity),
                this@MainActivity,
            ).also { it.connect() }
        }
    }

    // -- GatewayWebSocket.Listener（全部回调已在主线程） ------------------

    override fun onConnected() {
        failureCount = 0
        connectedAt = SystemClock.elapsedRealtime()
        // 曲线只代表"本次连接以来"，新连接建立时必须清空
        cards.values.forEach { it.clearSeries() }
        applyState(ConnectionUiState.ONLINE)
        appendLog(getString(R.string.log_ws_connected))
    }

    override fun onDisconnected(reason: String) {
        failureCount++
        applyState(
            if (failureCount >= FAILURES_BEFORE_ERROR) {
                ConnectionUiState.ERROR
            } else {
                ConnectionUiState.RECONNECTING
            }
        )
        // reason 里可能带底层异常原文（IP、端口、堆栈式描述），只进日志，不上状态栏
        appendLog(getString(R.string.log_ws_disconnected, reason))
    }

    override fun onData(data: RealtimeData) {
        receivedCount++
        lastDataAt = SystemClock.elapsedRealtime()
        if (state != ConnectionUiState.ONLINE) applyState(ConnectionUiState.ONLINE)

        val card = cards[data.channel]
        if (card == null) {
            // 其它通道本页不展示，但记录下来，便于确认链路确实收到了
            appendLog(
                getString(
                    R.string.log_other_channel,
                    data.channel,
                    ChannelFormat.value(data.value, data.channel),
                )
            )
        } else {
            card.updateValue(data)
        }
        pulseLiveDot()
        renderRealtimeLine()
    }

    override fun onAlarmStatus(status: AlarmStatus) {
        cards[status.channel]?.updateAlarm(status)
        if (status.triggered) {
            appendLog(
                getString(
                    R.string.log_alarm,
                    status.channel,
                    ChannelFormat.value(status.value, status.channel),
                    ChannelFormat.value(status.threshold, status.channel),
                )
            )
        }
    }

    override fun onStatistics(statistics: Statistics) {
        cards[statistics.channel]?.updateStatistics(statistics)
    }

    override fun onMalformedMessage(raw: String, error: String) {
        appendLog(getString(R.string.log_malformed, error))
    }

    override fun onUnknownMessage(type: String) {
        appendLog(getString(R.string.log_unknown, type))
    }

    // -- 状态渲染 -------------------------------------------------------

    private fun applyState(newState: ConnectionUiState) {
        state = newState
        val color = ContextCompat.getColor(this, newState.colorRes)
        binding.textStatus.setText(newState.labelRes)
        binding.textStatus.setTextColor(color)
        binding.statusDot.backgroundTintList = ColorStateList.valueOf(color)

        val liveColor = ContextCompat.getColor(
            this,
            if (newState.isLive) R.color.accent else R.color.state_idle,
        )
        binding.dotLive.backgroundTintList = ColorStateList.valueOf(liveColor)
        binding.textLive.setTextColor(liveColor)

        // 非在线状态下保留最后的数值但整卡降透明度：清空会让人误以为系统崩了
        cards.values.forEach { it.setStale(!newState.isLive) }
        renderRealtimeLine()
    }

    /**
     * 1 秒 tick：让"多久之前更新"这行字真的会走动，并检测数据停滞。
     *
     * 停滞检测解决的是一个界面看不出来的问题：WebSocket 假死时（TCP 没断、
     * 服务端不再推送）旧界面看起来一切正常。这里超过 10 秒无新数据就降级提示。
     */
    private fun onTick() {
        val stalled = StallDetector.isStalled(
            isOnline = state == ConnectionUiState.ONLINE,
            lastDataAt = lastDataAt,
            connectedAt = connectedAt,
            now = SystemClock.elapsedRealtime(),
            thresholdMs = STALL_THRESHOLD_MS,
        )
        if (stalled) {
            applyState(ConnectionUiState.STALLED)
            return
        }
        renderRealtimeLine()
    }

    private fun renderRealtimeLine() {
        binding.textRealtime.text = when {
            state == ConnectionUiState.STALLED ->
                getString(R.string.realtime_stalled, elapsedText(lastDataAt))

            !state.isLive -> getString(R.string.realtime_offline)

            receivedCount == 0 -> getString(R.string.realtime_waiting)

            else -> getString(R.string.realtime_updated, elapsedText(lastDataAt), receivedCount)
        }
    }

    /** 把"距离某个时刻过了多久"渲染成中文相对时间。 */
    private fun elapsedText(since: Long): String {
        if (since <= 0L) return getString(R.string.duration_seconds, 0)
        val seconds = ((SystemClock.elapsedRealtime() - since) / 1000L).toInt()
        return if (seconds < SECONDS_PER_MINUTE) {
            getString(R.string.duration_seconds, seconds)
        } else {
            getString(R.string.duration_minutes, seconds / SECONDS_PER_MINUTE)
        }
    }

    /**
     * 收到数据时闪一下。刻意**不做常驻循环动画**：只有真的有数据到达才闪，
     * 既省电，也让这个提示是诚实的（页面在动 == 数据在来）。
     */
    private fun pulseLiveDot() {
        binding.dotLive.animate().cancel()
        binding.dotLive.alpha = 1f
        binding.dotLive.animate()
            .alpha(PULSE_MIN_ALPHA)
            .setDuration(PULSE_HALF_MS)
            .withEndAction {
                binding.dotLive.animate().alpha(1f).setDuration(PULSE_HALF_MS).start()
            }
            .start()
    }

    // -- 设备状态 -------------------------------------------------------

    private fun renderDevices(statuses: List<Pair<String, DeviceStatus?>>) {
        binding.deviceContainer.removeAllViews()
        binding.textDeviceHint.visibility = View.GONE
        binding.textSubtitle.text = getString(
            R.string.home_subtitle_devices,
            getString(R.string.site_name),
            statuses.size,
        )

        primaryDeviceId = statuses.firstOrNull()?.first
        statuses.forEach { (deviceId, status) ->
            val row = ItemDeviceBinding.inflate(layoutInflater, binding.deviceContainer, true)
            row.textDeviceId.text = deviceId
            if (status == null) {
                row.textDeviceState.text = getString(R.string.device_status_failed)
                row.deviceDot.backgroundTintList = colorOf(R.color.state_idle)
            } else {
                val connection = getString(
                    if (status.isConnected) R.string.device_online else R.string.device_offline
                )
                val occupancy = if (status.isOccupied) {
                    getString(R.string.device_occupied, status.occupant.orEmpty())
                } else {
                    getString(R.string.device_idle)
                }
                row.textDeviceState.text = "$connection · $occupancy"
                row.deviceDot.backgroundTintList =
                    colorOf(if (status.isConnected) R.color.accent else R.color.state_idle)
            }
        }
    }

    private fun showDeviceHint(message: String) {
        binding.deviceContainer.removeAllViews()
        binding.textDeviceHint.visibility = View.VISIBLE
        binding.textDeviceHint.text = message
    }

    private fun colorOf(colorRes: Int) =
        ColorStateList.valueOf(ContextCompat.getColor(this, colorRes))

    // -- 运行日志 -------------------------------------------------------

    private fun toggleLog() {
        logExpanded = !logExpanded
        binding.textLog.visibility = if (logExpanded) View.VISIBLE else View.GONE
        binding.iconLogToggle.rotation = if (logExpanded) 180f else 0f
    }

    private fun appendLog(message: String) {
        logLines.addLast("[${timeFormat.format(Date())}] $message")
        while (logLines.size > MAX_LOG_LINES) logLines.removeFirst()
        renderLog()
    }

    private fun renderLog() {
        binding.textLog.text = if (logLines.isEmpty()) {
            getString(R.string.log_empty)
        } else {
            logLines.joinToString("\n")
        }
    }

    private companion object {
        const val MAX_LOG_LINES = 30
        const val MODE_SIMULATOR = "simulator"
        const val TICK_INTERVAL_MS = 1000L
        const val STALL_THRESHOLD_MS = StallDetector.DEFAULT_THRESHOLD_MS
        const val FAILURES_BEFORE_ERROR = 3
        const val SECONDS_PER_MINUTE = 60
        const val PULSE_HALF_MS = 120L
        const val PULSE_MIN_ALPHA = 0.3f
    }
}
