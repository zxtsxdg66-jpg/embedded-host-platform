package com.example.envmonitor

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.example.envmonitor.data.Channels
import com.example.envmonitor.data.GatewayClient
import com.example.envmonitor.data.HistoryPage
import com.example.envmonitor.databinding.ActivityHistoryBinding
import com.example.envmonitor.databinding.ItemHistoryRowBinding
import com.example.envmonitor.ui.ChannelFormat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 历史读数页。
 *
 * 查的是 **PC 端本地历史库**，经局域网网关的
 * `GET /devices/{id}/channels/{channel}/history`——手机不直连云端，
 * 也不在本机存任何历史（见 docs/02_Architecture/History_And_Cloud_Design.md 第 0 节）。
 * 因此关掉 App 再打开，看到的仍是 PC 上那一份，两端不会各存一份对不上的数据。
 *
 * 与问答页的两点不同，都是照这一页自己的情况定的，不是照抄：
 *
 * - **不开 WebSocket**。历史是过去的数据，不会自己变；需要最新的就下拉重查。
 *   少一条连接，页面也少一份要在 onDestroy 里收拾的状态。
 * - **一次只看一条通道**。三条通道混在一张表里，"某个时刻温度多少"这种问题反而
 *   难回答；顶部三个按钮切换，切换即重查。
 *
 * 仍然沿用问答页的做法：用 ScrollView + LinearLayout 逐条加视图，不引入
 * RecyclerView。三条理由，都不依赖"能不能编译验证"这件事（2026-09-17 已实测
 * 可以编译、可以跑单测，此前写在 build.gradle.kts 里的相反说法已订正）：
 *
 * - 与问答页保持同一种做法，两页的列表行为可以互相印证；
 * - RecyclerView 是一个**尚未缓存**的新依赖，离线环境下拿不到，
 *   而答辩前的构建不该为一个列表冒这种险；
 * - 200 行在 LinearLayout 里完全够用——这也是把查询上限定在 200 的原因，
 *   它是与这个取舍配套的数字，不是随手取的。
 */
class HistoryActivity : AppCompatActivity() {

    private lateinit var binding: ActivityHistoryBinding

    /** 当前正在看的通道。默认温度，与首页指标卡的排列顺序一致。 */
    private var channel: String = Channels.TEMPERATURE

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityHistoryBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.buttonBack.setOnClickListener { finish() }
        binding.buttonRefresh.setOnClickListener { load() }
        binding.chipTemperature.setOnClickListener { switchTo(Channels.TEMPERATURE) }
        binding.chipHumidity.setOnClickListener { switchTo(Channels.HUMIDITY) }
        binding.chipNoise.setOnClickListener { switchTo(Channels.NOISE) }

        updateChipStates()
        load()
    }

    private fun switchTo(target: String) {
        if (channel == target) return
        channel = target
        updateChipStates()
        load()
    }

    private fun updateChipStates() {
        binding.chipTemperature.isSelected = channel == Channels.TEMPERATURE
        binding.chipHumidity.isSelected = channel == Channels.HUMIDITY
        binding.chipNoise.isSelected = channel == Channels.NOISE
    }

    // -- 取数 ------------------------------------------------------------

    private fun load() {
        val deviceId = intent.getStringExtra(EXTRA_DEVICE_ID)
        if (deviceId.isNullOrBlank()) {
            // 首页还没拿到设备列表就点进来了。说清楚是什么状态，
            // 而不是显示一张空表让人以为"没有历史"。
            showMessage(getString(R.string.history_no_device))
            return
        }
        setLoading(true)
        val baseUrl = ServerConfig.httpBaseUrl(this)
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                GatewayClient(baseUrl).queryHistory(deviceId, channel)
            }
            setLoading(false)
            result
                .onSuccess { render(it) }
                // 失败原因照实说出来（PC 没开、IP 填错、不在同一局域网都长得不一样），
                // 这是 GatewayClient 返回 Result 而不是抛异常的全部意义。
                .onFailure {
                    showMessage(
                        getString(R.string.history_failed, it.message ?: "")
                    )
                }
        }
    }

    private fun render(page: HistoryPage) {
        binding.containerRows.removeAllViews()
        if (page.points.isEmpty()) {
            showMessage(getString(R.string.history_empty))
            return
        }
        binding.textMessage.visibility = View.GONE
        // 服务端按"新的在前"返回，这里原样显示：最近发生的事排在最上面，
        // 与桌面端历史表自上而下顺着时间读是相反的取向——手机上翻到底
        // 才看到最新一条会很别扭。
        page.points.forEach { point ->
            val row = ItemHistoryRowBinding.inflate(
                LayoutInflater.from(this), binding.containerRows, false
            )
            row.textTime.text = ChannelFormat.moment(point.timestamp)
            // 按通道定小数位，不写死两位：湿度传感器精度约 ±2%，
            // 显示 "58.00 %" 是虚假精度（见 ChannelFormat 的注释）。
            row.textValue.text = getString(
                R.string.history_value,
                ChannelFormat.value(point.value, page.channel),
                page.unit,
            )
            row.textFlag.visibility = if (point.valid) View.GONE else View.VISIBLE
            binding.containerRows.addView(row.root)
        }
        binding.textSummary.text =
            getString(R.string.history_summary, page.points.size)
        binding.textSummary.visibility = View.VISIBLE
    }

    private fun showMessage(message: String) {
        binding.containerRows.removeAllViews()
        binding.textSummary.visibility = View.GONE
        binding.textMessage.text = message
        binding.textMessage.visibility = View.VISIBLE
    }

    private fun setLoading(loading: Boolean) {
        binding.buttonRefresh.isEnabled = !loading
        if (loading) {
            showMessage(getString(R.string.history_loading))
        }
    }

    companion object {
        const val EXTRA_DEVICE_ID = "device_id"
    }
}
