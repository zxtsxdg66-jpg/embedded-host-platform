package com.example.envmonitor

import android.content.Context

/**
 * PC 网关地址配置。
 *
 * 刻意不硬编码 localhost/127.0.0.1：那两个地址在手机上指向手机自己，永远连不到 PC。
 * 真机测试时必须填 PC 在局域网中的实际 IP（Windows 下用 `ipconfig` 查看 IPv4 地址）。
 *
 * 地址持久化在 SharedPreferences 里，改一次之后重启 App 仍然有效，不需要重新编译。
 */
object ServerConfig {

    private const val PREFS_NAME = "env_monitor_prefs"
    private const val KEY_HOST = "pc_host"
    private const val KEY_PORT = "pc_port"

    /**
     * 默认值填的是 10.0.2.2 —— 这是 Android 模拟器访问"宿主机 PC"的专用回环地址。
     * 用模拟器测试时开箱即用；用真机测试时必须在界面上改成 PC 的局域网 IP。
     */
    private const val DEFAULT_HOST = "10.0.2.2"
    private const val DEFAULT_PORT = 8000

    fun host(context: Context): String =
        prefs(context).getString(KEY_HOST, DEFAULT_HOST) ?: DEFAULT_HOST

    fun port(context: Context): Int = prefs(context).getInt(KEY_PORT, DEFAULT_PORT)

    fun save(context: Context, host: String, port: Int) {
        prefs(context).edit()
            .putString(KEY_HOST, host.trim())
            .putInt(KEY_PORT, port)
            .apply()
    }

    fun httpBaseUrl(context: Context): String = "http://${host(context)}:${port(context)}"

    fun webSocketUrl(context: Context): String = "ws://${host(context)}:${port(context)}/ws"

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
}
