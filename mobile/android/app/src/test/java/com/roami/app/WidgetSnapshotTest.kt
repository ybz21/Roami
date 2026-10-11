package com.roami.app

import org.junit.Assert.assertEquals
import org.junit.Test

class WidgetSnapshotTest {
    private fun session(name: String) = WidgetSession(name, name, "project")

    @Test fun mixedStatesKeepBothVisible() {
        val snapshot = WidgetSnapshot(3, 3, listOf(session("run1"), session("run2"), session("run3")),
            listOf(session("wait1"), session("wait2"), session("wait3")), 0)
        assertEquals(listOf("wait1", "run1"), snapshot.rows(2).map { it.session.name })
        assertEquals(listOf("wait1", "wait2", "run1", "run2"), snapshot.rows(4).map { it.session.name })
    }

    @Test fun oneStateUsesEveryAvailableRow() {
        val snapshot = WidgetSnapshot(0, 3, emptyList(),
            listOf(session("wait1"), session("wait2"), session("wait3")), 0)
        assertEquals(listOf("wait1", "wait2", "wait3"), snapshot.rows(3).map { it.session.name })
    }
}
