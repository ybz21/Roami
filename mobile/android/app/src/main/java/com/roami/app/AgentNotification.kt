package com.roami.app

import org.json.JSONObject

object AgentNotification {
    private val id = Regex("^[A-Za-z0-9_-]{1,200}$")

    fun path(event: JSONObject): String {
        val parts = listOf("conversation", "branch", "message").map { event.optString(it) }
        return if (parts.all { id.matches(it) }) "/#/home/" + parts.joinToString("/") else "/#/home"
    }

    fun key(event: JSONObject): String = "agent:" + event.optString("conversation")
}
