package com.example.envmonitor.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.util.AttributeSet
import android.view.View
import androidx.core.content.ContextCompat
import com.example.envmonitor.R

/**
 * 极简折线图：只画"本次连接以来 App 自己收到的点"。
 *
 * **它画的不是历史数据。** PC 端 `service`/`api` 三层没有历史数据能力
 * （见 docs/05_Test/Project_Status_Context.md 5.3 节第 2 项），本视图的每个点
 * 都是 WebSocket 当场推过来、App 顺手记在内存里的，断开重连即清空，
 * 卡片上固定标注"本次连接以来"。不要把它当成历史曲线，也不要给它加持久化。
 *
 * 刻意自绘而不引入 MPAndroidChart 等第三方图表库：需求只有"一条线"，
 * 与 PC 端 `ui/widgets/chart_widget.py` 同样手绘的做法保持一致，
 * 也避免为一个装饰性元素引入一个大依赖。
 */
class SparklineView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : View(context, attrs, defStyleAttr) {

    private val values = ArrayDeque<Float>()
    private val path = Path()
    private val fillPath = Path()

    private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        strokeWidth = dp(1.5f)
    }

    /** 线下方的低透明填充。只有一层纯色透明，不做渐变。 */
    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
    }

    private val dotPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
    }

    private val baselinePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = dp(1f)
        color = ContextCompat.getColor(context, R.color.stroke_card)
    }

    init {
        setLineColor(ContextCompat.getColor(context, R.color.accent))
    }

    /** 曲线颜色。报警时由 [MetricCardView] 改成报警红，与卡片其余部分保持一致。 */
    fun setLineColor(color: Int) {
        linePaint.color = color
        dotPaint.color = color
        fillPaint.color = color and 0x00FFFFFF or (FILL_ALPHA shl 24)
        invalidate()
    }

    fun addPoint(value: Float) {
        if (values.size >= MAX_POINTS) values.removeFirst()
        values.addLast(value)
        invalidate()
    }

    /** 断开/重连时调用：本次连接结束，之前的点不再属于"本次连接以来"。 */
    fun clear() {
        values.clear()
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        val w = width.toFloat()
        val h = height.toFloat()
        if (w <= 0f || h <= 0f) return

        // 点数不足以成线时画一条基准线，避免空白区域看起来像"渲染失败"
        if (values.size < 2) {
            canvas.drawLine(0f, h / 2f, w, h / 2f, baselinePaint)
            return
        }

        val minimum = values.min()
        val maximum = values.max()
        val span = maximum - minimum

        val padding = dp(3f)
        val usableHeight = h - padding * 2f
        val stepX = w / (values.size - 1)

        // 全部取值相同时（span≈0）画水平中线，而不是除零
        fun yOf(value: Float): Float =
            if (span < EPSILON) h / 2f else padding + (1f - (value - minimum) / span) * usableHeight

        path.reset()
        fillPath.reset()
        var lastX = 0f
        var lastY = 0f
        values.forEachIndexed { index, value ->
            val x = index * stepX
            val y = yOf(value)
            if (index == 0) {
                path.moveTo(x, y)
                fillPath.moveTo(x, h)
                fillPath.lineTo(x, y)
            } else {
                path.lineTo(x, y)
                fillPath.lineTo(x, y)
            }
            lastX = x
            lastY = y
        }
        fillPath.lineTo(lastX, h)
        fillPath.close()

        canvas.drawPath(fillPath, fillPaint)
        canvas.drawPath(path, linePaint)
        // 末端点：一眼看出"最新值在这里"
        canvas.drawCircle(lastX, lastY, dp(2.5f), dotPaint)
    }

    private fun dp(value: Float): Float = value * resources.displayMetrics.density

    private companion object {
        /** 保留最近 60 个点：3 秒一轮采集约合 3 分钟窗口，够看出趋势又不占内存。 */
        const val MAX_POINTS = 60
        const val FILL_ALPHA = 0x24
        const val EPSILON = 1e-6f
    }
}
