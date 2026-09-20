package com.example.envmonitor

import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.example.envmonitor.databinding.ActivitySettingsBinding

/**
 * 连接设置页：PC 网关地址的查看与修改。
 *
 * 刻意**只负责保存地址**，不持有也不操作 WebSocket —— 连接的建立/断开全部留在
 * [MainActivity]，它在 `onResume` 里比较地址有没有变来决定要不要重连。
 * 这样第二阶段就不需要为了"跨页面控制连接"去改动已经真机验证过的
 * `data/GatewayWebSocket.kt`。
 */
class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.inputHost.setText(ServerConfig.host(this))
        binding.inputPort.setText(ServerConfig.port(this).toString())
        renderCurrentAddress()
        binding.textVersion.text = getString(R.string.settings_version, versionName())

        binding.buttonBack.setOnClickListener { finish() }
        binding.buttonSave.setOnClickListener { save() }
    }

    private fun save() {
        val host = binding.inputHost.text?.toString()?.trim().orEmpty()
        val port = binding.inputPort.text?.toString()?.trim()?.toIntOrNull()

        binding.layoutHost.error = null
        binding.layoutPort.error = null

        if (host.isEmpty()) {
            binding.layoutHost.error = getString(R.string.settings_error_host)
            return
        }
        if (port == null || port !in MIN_PORT..MAX_PORT) {
            binding.layoutPort.error = getString(R.string.settings_error_port)
            return
        }

        ServerConfig.save(this, host, port)
        renderCurrentAddress()
        Toast.makeText(this, R.string.settings_saved, Toast.LENGTH_SHORT).show()
        finish()
    }

    private fun renderCurrentAddress() {
        binding.textCurrent.text =
            getString(R.string.settings_current, ServerConfig.httpBaseUrl(this))
    }

    /**
     * 从 PackageManager 读版本号，而不是用 BuildConfig —— AGP 8 默认不生成
     * BuildConfig 类，为一行版本号去打开 `buildConfig` 特性不划算。
     */
    private fun versionName(): String = runCatching {
        packageManager.getPackageInfo(packageName, 0).versionName.orEmpty()
    }.getOrDefault("")

    private companion object {
        const val MIN_PORT = 1
        const val MAX_PORT = 65535
    }
}
