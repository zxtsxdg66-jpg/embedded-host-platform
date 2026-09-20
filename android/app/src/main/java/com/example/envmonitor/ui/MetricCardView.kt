package com.example.envmonitor.ui

import android.animation.ArgbEvaluator
import android.animation.ValueAnimator
import android.content.Context
import android.content.res.ColorStateList
import android.util.AttributeSet
import android.view.LayoutInflater
import android.view.View
import androidx.core.content.ContextCompat
import com.example.envmonitor.R
import com.example.envmonitor.data.AlarmStatus
import com.example.envmonitor.data.RealtimeData
import com.example.envmonitor.data.Statistics
import com.example.envmonitor.databinding.ViewMetricCardBinding
import com.google.android.material.card.MaterialCardView

/**
 * 一个环境指标卡（温度 / 湿度 / 噪声各一张）。
 *
 * 只消费 [RealtimeData] / [AlarmStatus] / [Statistics] 三个**已有**模型，
 * 不新增字段、不发起任何网络请求——所有数据都由 MainActivity 从
 * GatewayWebSocket 的回调里转发进来。
 */
class MetricCardView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = com.google.android.material.R.attr.materialCardViewOutlinedStyle,
) : MaterialCardView(context, attrs, defStyleAttr) {

    private val binding = ViewMetricCardBinding.inflate(LayoutInflater.from(context), this)

    private val colorPrimary = ContextCompat.getColor(context, R.color.text_primary)
    private val colorAccent = ContextCompat.getColor(context, R.color.accent)
    private val colorAlarm = ContextCompat.getColor(context, R.color.state_alarm)
    private val colorIdle = ContextCompat.getColor(context, R.color.state_idle)
    private val colorStroke = ContextCompat.getColor(context, R.color.stroke_card)
    private val strokeNormalPx = resources.getDimensionPixelSize(R.dimen.stroke_width)

    private var channel: String = ""
    private var alarmTriggered = false
    private var highlight: ValueAnimator? = null

    /** 绑定通道。名称由调用方给，卡片自己不认识"温度"这类业务语义。 */
    fun setup(channel: String, name: String) {
        this.channel = channel
        binding.textName.text = name
        showWaiting()
    }

    /** 空状态：还没收到过任何数据。 */
    fun showWaiting() {
        binding.textValue.text = context.getString(R.string.value_placeholder)
        binding.textUnit.text = ""
        binding.textStatsRange.text = ""
        binding.textStatsAverage.text = ""
        setStatus(colorIdle, R.string.metric_waiting)
        applyAlarm(triggered = false)
    }

    fun updateValue(data: RealtimeData) {
        binding.textValue.text = ChannelFormat.value(data.value, channel)
        binding.textUnit.text = data.unit
        binding.sparkline.addPoint(data.value.toFloat())
        // 尚未收到该通道的 alarm_status 时，先按"正常"呈现，避免一直停在灰色等待态
        if (!alarmTriggered && binding.textStatus.text == context.getString(R.string.metric_waiting)) {
            setStatus(colorAccent, R.string.metric_normal)
        }
        flashValue()
    }

    fun updateStatistics(statistics: Statistics) {
        binding.textStatsRange.text = context.getString(
            R.string.metric_stats_range,
            ChannelFormat.value(statistics.minimum, channel),
            ChannelFormat.value(statistics.maximum, channel),
        )
        binding.textStatsAverage.text = context.getString(
            R.string.metric_stats_average,
            ChannelFormat.value(statistics.average, channel),
            statistics.sampleCount,
        )
    }

    fun updateAlarm(status: AlarmStatus) {
        applyAlarm(status.triggered)
        if (status.triggered) {
            val template = if (status.kind == KIND_BELOW_MIN) {
                R.string.metric_threshold_below
            } else {
                R.string.metric_threshold_above
            }
            binding.textThreshold.text = context.getString(
                template,
                ChannelFormat.value(status.threshold, channel),
                status.unit,
            )
        }
    }

    /** 本次连接结束：曲线只代表"本次连接以来"，必须清空。 */
    fun clearSeries() = binding.sparkline.clear()

    /**
     * 数据停止更新时整卡降到 60% 透明度——保留最后一次的值而不是清空，
     * 清空会让人误以为系统崩了；降透明度则明确表示"这是旧值"。
     */
    fun setStale(stale: Boolean) {
        alpha = if (stale) STALE_ALPHA else 1f
    }

    private fun applyAlarm(triggered: Boolean) {
        alarmTriggered = triggered
        if (triggered) {
            setStatus(colorAlarm, R.string.metric_alarm)
            binding.textValue.setTextColor(colorAlarm)
            binding.textThreshold.visibility = View.VISIBLE
            binding.sparkline.setLineColor(colorAlarm)
            strokeColor = colorAlarm
            strokeWidth = strokeNormalPx * 2
        } else {
            binding.textValue.setTextColor(colorPrimary)
            binding.textThreshold.visibility = View.GONE
            binding.sparkline.setLineColor(colorAccent)
            strokeColor = colorStroke
            strokeWidth = strokeNormalPx
            if (binding.textStatus.text != context.getString(R.string.metric_waiting)) {
                setStatus(colorAccent, R.string.metric_normal)
            }
        }
    }

    private fun setStatus(color: Int, textRes: Int) {
        binding.statusDot.backgroundTintList = ColorStateList.valueOf(color)
        binding.textStatus.setText(textRes)
    }

    /**
     * 数值变化时用 300ms 从强调色过渡回正常色，让"这条数刚刚变了"可见。
     * 报警状态下不做（红色必须稳定存在），也刻意不做数字滚动/卡片缩放——
     * 数据 3 秒一轮，动画必须远短于更新间隔，否则界面永远在动，久看会累。
     */
    private fun flashValue() {
        if (alarmTriggered) return
        highlight?.cancel()
        highlight = ValueAnimator.ofObject(ArgbEvaluator(), colorAccent, colorPrimary).apply {
            duration = HIGHLIGHT_DURATION_MS
            addUpdateListener { animator ->
                if (!alarmTriggered) binding.textValue.setTextColor(animator.animatedValue as Int)
            }
            start()
        }
    }

    override fun onDetachedFromWindow() {
        highlight?.cancel()
        highlight = null
        super.onDetachedFromWindow()
    }

    private companion object {
        const val KIND_BELOW_MIN = "BELOW_MIN"
        const val HIGHLIGHT_DURATION_MS = 300L
        const val STALE_ALPHA = 0.6f
    }
}
