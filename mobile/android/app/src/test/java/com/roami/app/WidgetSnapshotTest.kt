package com.roami.app

import org.junit.Assert.assertEquals
import org.junit.Test
import org.json.JSONArray

class WidgetSnapshotTest {
    private fun session(name: String) = WidgetSession(name, name, "project")

    @Test fun overviewRecoversPromptAndAllChoicesAfterReconnect() {
        val snapshot = WidgetSnapshot.fromOverview(JSONArray("""[
            {"name":"s","label":"Task","waiting":true,"prompt":"current",
             "waitingBody":"Choose a release","choices":[{"value":"1","label":"Stable"},{"value":"2","label":"Beta"}]}
        ]"""))
        val task = snapshot.waitingItems.single()
        assertEquals("current", task.prompt)
        assertEquals("Choose a release", task.waitingBody)
        assertEquals(listOf("Stable", "Beta"), task.choices.map { it.label })
    }

    @Test fun overviewCountsBusyAgentsNotIdleProcesses() {
        val items = JSONArray("""[
            {"name":"pi-busy","label":"Pi busy","project":"P","agent":"pi","running":true,"waiting":false},
            {"name":"pi-idle","label":"Pi idle","project":"P","agent":"pi","running":false,"waiting":false},
            {"name":"codex-busy","label":"Codex busy","project":"C","agent":"codex","running":true,"waiting":false}
        ]""")
        val snapshot = WidgetSnapshot.fromOverview(items)
        assertEquals(2, snapshot.running)
        assertEquals(listOf("pi-busy", "codex-busy"), snapshot.runningItems.map { it.name })
    }

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

    @Test fun attentionIncludesUnfinishedWorktrees() {
        val projects = JSONArray("""[
            {"name":"a","unfinished":2}, {"name":"b","unfinished":5}, {"name":"c","unfinished":0}
        ]""")
        val snapshot = WidgetSnapshot(1, 3, emptyList(), emptyList(), 0,
            WidgetSnapshot.unfinishedFromProjects(projects))
        assertEquals(7, snapshot.unfinished)
        assertEquals(10, snapshot.attentionCount)
    }
}
