package com.roami.app

import org.json.JSONArray
import org.json.JSONObject

class TaskEventRecovery(saved: JSONObject = JSONObject()) {
    private var cursor = saved.optLong("cursor", -1)
    private val delivered = linkedSetOf<Long>().apply {
        saved.optJSONArray("delivered")?.let { rows ->
            for (i in 0 until rows.length()) add(rows.optLong(i))
        }
    }

    fun accept(id: Long): Boolean {
        if (id <= 0) return true
        if (!delivered.add(id)) return false
        while (delivered.size > 128) delivered.remove(delivered.first())
        return true
    }

    fun recover(rows: JSONArray, nowSeconds: Long, running: Set<String>): List<JSONObject> {
        val items = (0 until rows.length()).mapNotNull { rows.optJSONObject(it) }
        val latest = items.maxOfOrNull { it.optLong("id") } ?: 0
        if (cursor < 0) { cursor = latest; return emptyList() }
        val previous = cursor
        cursor = maxOf(cursor, latest)
        // Overview restores current approvals; only recover the newest terminal state per task.
        return items.sortedByDescending { it.optLong("id") }
            .distinctBy { it.optString("session") }
            .filter {
                it.optLong("id") > previous && it.optLong("id") !in delivered &&
                    it.optLong("at") >= nowSeconds - 600 && it.optString("session").isNotBlank() &&
                    (it.optString("type") == "session.done" ||
                        it.optString("type") == "session.error" && it.optString("session") !in running)
            }.sortedBy { it.optLong("id") }
    }

    fun snapshot(): String = JSONObject().put("cursor", cursor)
        .put("delivered", JSONArray(delivered.toList())).toString()
}
