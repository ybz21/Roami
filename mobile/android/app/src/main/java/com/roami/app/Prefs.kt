package com.roami.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/** 环境列表、当前环境、信任过的证书指纹。都是小数据，SharedPreferences 够用。 */
class Prefs(ctx: Context) {
    private val sp = ctx.getSharedPreferences("roami", Context.MODE_PRIVATE)

    data class Server(val name: String, val url: String)

    var servers: List<Server>
        get() = runCatching {
            val arr = JSONArray(sp.getString("servers", "[]"))
            (0 until arr.length()).map { i -> arr.getJSONObject(i).let { Server(it.getString("name"), it.getString("url")) } }
        }.getOrDefault(emptyList())
        set(v) {
            val arr = JSONArray()
            v.forEach { arr.put(JSONObject().put("name", it.name).put("url", it.url)) }
            sp.edit().putString("servers", arr.toString()).apply()
        }

    var current: String?
        get() = sp.getString("current", null)
        set(v) = sp.edit().putString("current", v).apply()

    /** 首次进来倒计时自动进入；用户手动取消过一次就这次不再自动 */
    fun remember(url: String) {
        val name = runCatching { java.net.URI(url).host ?: url }.getOrDefault(url)
        servers = listOf(Server(name, url)) + servers.filter { it.url != url }
        current = url
    }

    fun forget(url: String) {
        servers = servers.filter { it.url != url }
        if (current == url) current = null
    }

    fun trusted(host: String): String? = sp.getString("fp:$host", null)
    fun trust(host: String, fp: String) = sp.edit().putString("fp:$host", fp).apply()

    fun taskEvents(base: String): TaskEventRecovery = TaskEventRecovery(runCatching {
        JSONObject(sp.getString("task-events:$base", "{}") ?: "{}")
    }.getOrDefault(JSONObject()))

    fun saveTaskEvents(base: String, recovery: TaskEventRecovery) {
        sp.edit().putString("task-events:$base", recovery.snapshot()).apply()
    }

    fun taskCards(base: String): List<CapsuleTask> = TaskNoticeIndex.decode(sp.getString("task-cards:$base", "[]") ?: "[]")

    fun saveTaskCards(base: String, tasks: List<CapsuleTask>): Boolean {
        val value = TaskNoticeIndex.encode(tasks)
        if (sp.getString("task-cards:$base", "[]") == value) return false
        sp.edit().putString("task-cards:$base", value).apply()
        return true
    }
}
