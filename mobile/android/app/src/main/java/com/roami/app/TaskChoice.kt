package com.roami.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

data class TaskChoice(val value: String, val label: String) {
    fun label(ctx: Context): String = label.ifBlank {
        when (value) { "yes" -> ctx.getString(R.string.act_allow); "no" -> ctx.getString(R.string.act_deny); else -> value }
    }

    companion object {
        fun read(rows: JSONArray?): List<TaskChoice> = if (rows == null) emptyList() else
            (0 until rows.length()).mapNotNull { i -> rows.optJSONObject(i)?.let {
                val value = it.optString("value")
                if (value.isBlank()) null else TaskChoice(value, it.optString("label"))
            } }

        fun encode(choices: List<TaskChoice>): String = JSONArray().apply {
            choices.forEach { put(JSONObject().put("value", it.value).put("label", it.label)) }
        }.toString()
    }
}
