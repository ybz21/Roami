package com.roami.app

import org.junit.Assert.assertEquals
import org.junit.Test

class WidgetSnapshotTest {
    private fun session(name: String) = WidgetSession(name, name, "project")

    @Test fun runningSessionsRotateWithoutWaitingTakingTheirPlace() {
        val snapshot = WidgetSnapshot(3, 3, listOf(session("run1"), session("run2"), session("run3")),
            listOf(session("wait1"), session("wait2"), session("wait3")), 0)
        assertEquals(listOf("run1", "run2", "run3"), snapshot.carouselRows().map { it.session.name })
        assertEquals(listOf(false, false, false), snapshot.carouselRows().map { it.waiting })
    }

    @Test fun waitingSessionAppearsWhenNothingRuns() {
        val snapshot = WidgetSnapshot(0, 3, emptyList(),
            listOf(session("wait1"), session("wait2"), session("wait3")), 0)
        assertEquals(listOf("wait1"), snapshot.carouselRows().map { it.session.name })
        assertEquals(true, snapshot.carouselRows().single().waiting)
    }
}
