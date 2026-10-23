package com.roami.app

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TaskEventRecoveryTest {
    private fun event(id: Long, type: String = "session.done", session: String = "s", at: Long = 1000) =
        JSONObject().put("id", id).put("type", type).put("session", session).put("at", at)

    @Test fun firstInstallDoesNotReplayHistory() {
        val recovery = TaskEventRecovery()
        assertTrue(recovery.recover(JSONArray().put(event(4)), 1000, emptySet()).isEmpty())
        assertEquals(5L, recovery.recover(JSONArray().put(event(5)).put(event(4)), 1001, emptySet()).single().optLong("id"))
    }

    @Test fun reconnectRestoresMissedCompletionAcrossServiceRestart() {
        val before = TaskEventRecovery()
        before.recover(JSONArray().put(event(4)), 1000, emptySet())
        val after = TaskEventRecovery(JSONObject(before.snapshot()))
        assertEquals(5L, after.recover(JSONArray().put(event(5)).put(event(4)), 1001, emptySet()).single().optLong("id"))
    }

    @Test fun liveDeliveryDoesNotHideEarlierMissedEventOrRepeatItself() {
        val recovery = TaskEventRecovery()
        recovery.recover(JSONArray().put(event(4)), 1000, emptySet())
        recovery.accept(6)
        val pending = recovery.recover(JSONArray().put(event(6, session = "live")).put(event(5, session = "missed")), 1001, emptySet())
        assertEquals(listOf(5L), pending.map { it.optLong("id") })
        recovery.accept(5)
        val restarted = TaskEventRecovery(JSONObject(recovery.snapshot()))
        assertTrue(restarted.recover(JSONArray().put(event(6)).put(event(5)), 1002, emptySet()).isEmpty())
    }

    @Test fun newerApprovalAndResumedTaskSuppressStaleTerminalEvents() {
        val recovery = TaskEventRecovery()
        recovery.recover(JSONArray(), 1000, emptySet())
        val rows = JSONArray().put(event(3, "session.waiting")).put(event(2))
            .put(event(4, "session.error", "resumed")).put(event(5, session = "ancient", at = 1))
        assertTrue(recovery.recover(rows, 1001, setOf("resumed")).isEmpty())
    }
}
