package com.example.envmonitor

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.example.envmonitor.data.AlarmStatus
import com.example.envmonitor.data.AssistantAnswer
import com.example.envmonitor.data.GatewayClient
import com.example.envmonitor.data.GatewayWebSocket
import com.example.envmonitor.data.RealtimeData
import com.example.envmonitor.data.Statistics
import com.example.envmonitor.databinding.ActivityAssistantBinding
import com.example.envmonitor.databinding.ItemChatBubbleBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 环境问答页。
 *
 * 与 PC 端问答面板同源：问句发给网关的 `POST /assistant/ask`，立刻拿到规则与模板
 * 生成的答案；PC 端若接了本地模型，改写后的答案（或"模型读懂了规则没认出的问句"
 * 那一条）会在数秒后经 WebSocket 补送，此时**替换**刚才那条气泡，而不是再加一条。
 * 两条是同一个问题的两个版本，并排显示会让人以为系统答了两次。
 *
 * 为什么自己开一条 WebSocket，而不是从 [MainActivity] 转发：
 * 首页的连接流程与线程调度是第一阶段真机验证过的，为了跨页面传一条消息去改它
 * 不划算；而网关的事件扇出本来就支持多个订阅者，每个订阅者有独立队列
 * （见 `src/gateway/event_hub.py`）。代价只是问答页开着时多一条连接。
 *
 * 本页不处理 data / alarm / statistics 三类消息——它们照常发到这条连接上，
 * 这里直接忽略，那是首页的职责。
 */
class AssistantActivity : AppCompatActivity(), GatewayWebSocket.Listener {

    private lateinit var binding: ActivityAssistantBinding
    private var webSocket: GatewayWebSocket? = null

    /** 最近一条答案气泡；模型补送时替换它的内容。null 表示当前没有待替换的答案。 */
    private var pendingAnswer: ItemChatBubbleBinding? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityAssistantBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.buttonBack.setOnClickListener { finish() }
        binding.buttonSend.setOnClickListener { send() }
        binding.inputQuestion.setOnEditorActionListener { _, _, _ ->
            send()
            true
        }

        addSystemLine(getString(R.string.assistant_greeting))

        webSocket = GatewayWebSocket(ServerConfig.webSocketUrl(this), this).also { it.connect() }
    }

    override fun onDestroy() {
        super.onDestroy()
        webSocket?.close()
        webSocket = null
    }

    // -- 提问 ------------------------------------------------------------

    private fun send() {
        val question = binding.inputQuestion.text?.toString()?.trim().orEmpty()
        if (question.isEmpty()) return

        binding.inputQuestion.setText("")
        addBubble(question, isUser = true, source = null)
        setSending(true)

        val baseUrl = ServerConfig.httpBaseUrl(this)
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) { GatewayClient(baseUrl).ask(question) }
            setSending(false)
            result.fold(
                onSuccess = { answer ->
                    // 记下这条气泡：模型的改写若在几秒后到达，就地替换它。
                    pendingAnswer = addBubble(answer.text, isUser = false, source = answer.source)
                },
                onFailure = { error ->
                    pendingAnswer = null
                    addSystemLine(
                        getString(R.string.assistant_failed, error.message ?: "未知错误")
                    )
                },
            )
        }
    }

    private fun setSending(sending: Boolean) {
        binding.buttonSend.isEnabled = !sending
        binding.inputQuestion.isEnabled = !sending
        binding.textThinking.visibility = if (sending) View.VISIBLE else View.GONE
    }

    // -- WebSocket 回调 ---------------------------------------------------

    override fun onAssistantAnswer(answer: AssistantAnswer) {
        val bubble = pendingAnswer
        if (bubble == null) {
            // 没有待替换的气泡（例如刚进页面就收到上一轮的补送），当作新答案追加，
            // 总好过静默丢弃一条真实答案。
            addBubble(answer.text, isUser = false, source = answer.source)
            return
        }
        bubble.textBubble.text = answer.text
        bubble.textSource.text = sourceLabel(answer.source)
        pendingAnswer = null
        scrollToBottom()
    }

    override fun onConnected() {
        binding.textConnection.text = getString(R.string.assistant_ws_connected)
    }

    override fun onDisconnected(reason: String) {
        binding.textConnection.text = getString(R.string.assistant_ws_disconnected, reason)
    }

    // 首页负责的三类消息，这里不处理。
    override fun onData(data: RealtimeData) = Unit

    override fun onAlarmStatus(status: AlarmStatus) = Unit

    override fun onStatistics(statistics: Statistics) = Unit

    override fun onMalformedMessage(raw: String, error: String) = Unit

    override fun onUnknownMessage(type: String) = Unit

    // -- 气泡 ------------------------------------------------------------

    private fun addBubble(
        text: String,
        isUser: Boolean,
        source: String?,
    ): ItemChatBubbleBinding {
        val item = ItemChatBubbleBinding.inflate(
            LayoutInflater.from(this), binding.containerMessages, false
        )
        item.textBubble.text = text
        item.textSource.text = if (isUser) getString(R.string.assistant_role_user)
        else sourceLabel(source)
        item.root.gravity = if (isUser) android.view.Gravity.END else android.view.Gravity.START
        item.textBubble.setBackgroundResource(
            if (isUser) R.drawable.bg_bubble_user else R.drawable.bg_bubble_assistant
        )
        binding.containerMessages.addView(item.root)
        scrollToBottom()
        return item
    }

    private fun addSystemLine(text: String) {
        val item = ItemChatBubbleBinding.inflate(
            LayoutInflater.from(this), binding.containerMessages, false
        )
        item.textBubble.text = text
        item.textSource.visibility = View.GONE
        item.textBubble.setBackgroundResource(R.drawable.bg_bubble_assistant)
        binding.containerMessages.addView(item.root)
        scrollToBottom()
    }

    /**
     * 来源标签。四种取值分开显示而不是笼统写"AI"，是因为它们对读者的意义不同：
     * 「模型改写」只动了措辞，「模型识别」是模型判断了问题类别、句子仍是程序写的，
     * 分不清这两者就无法判断该信多少。与 PC 端问答面板的标签保持一致。
     */
    private fun sourceLabel(source: String?): String = when (source) {
        AssistantAnswer.SOURCE_MODEL -> getString(R.string.assistant_source_model)
        AssistantAnswer.SOURCE_MODEL_INTENT -> getString(R.string.assistant_source_model_intent)
        AssistantAnswer.SOURCE_FALLBACK -> getString(R.string.assistant_source_fallback)
        else -> getString(R.string.assistant_source_template)
    }

    private fun scrollToBottom() {
        binding.scrollMessages.post {
            binding.scrollMessages.fullScroll(View.FOCUS_DOWN)
        }
    }
}
