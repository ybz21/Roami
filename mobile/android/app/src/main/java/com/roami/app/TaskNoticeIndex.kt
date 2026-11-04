package com.roami.app

import org.json.JSONArray
import org.json.JSONObject

object TaskNoticeIndex {
    fun encode(tasks: List<CapsuleTask>): String = JSONArray().apply {
        tasks.forEach { task -> put(JSONObject().put("session", task.session).put("title", task.title)
            .put("body", task.body).put("state", task.state.name).put("selectionMode", task.selectionMode)
            .put("choices", JSONArray(TaskChoice.encode(task.choices)))) }
    }.toString()

    fun decode(value: String): List<CapsuleTask> = runCatching {
        val rows = JSONArray(value)
        (0 until rows.length()).mapNotNull { i ->
            val row = rows.optJSONObject(i) ?: return@mapNotNull null
            val session = row.optString("session").takeIf { it.isNotBlank() } ?: return@mapNotNull null
            val state = runCatching { TaskNoticeState.valueOf(row.optString("state")) }.getOrNull() ?: return@mapNotNull null
            CapsuleTask(session, row.optString("title"), row.optString("body"), state,
                choices = TaskChoice.read(row.optJSONArray("choices")), selectionMode = row.optString("selectionMode", "single"))
        }
    }.getOrDefault(emptyList())
}
