package com.roami.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TaskCapsuleStateTest {
    private fun task(session: String, state: TaskNoticeState) = CapsuleTask(session, session, "detail", state)

    @Test fun waitingPreemptsCompletionThenCompletionExpires() {
        val state = TaskCapsuleState()
        state.onSnapshot(emptyList(), 1)
        assertNull(state.current(1))
        state.onEvent(task("done", TaskNoticeState.FINISHED), 1, 2)
        state.onEvent(task("approval", TaskNoticeState.WAITING), 2, 3)
        assertEquals("approval", state.current(3)?.session)
        state.resolve("approval", 4)
        assertEquals("done", state.current(4)?.session)
        assertNull(state.current(4 + TaskCapsuleState.FLASH_MS))
    }

    @Test fun resolvedWaitingDoesNotReturnFromStaleSnapshot() {
        val state = TaskCapsuleState()
        val waiting = listOf(task("approval", TaskNoticeState.WAITING))
        state.onSnapshot(waiting, 1)
        state.resolve("approval", 2)
        state.onSnapshot(waiting, 3)
        assertNull(state.current(3))
    }

    @Test fun repeatedEventDoesNotRestartCompletionPill() {
        val state = TaskCapsuleState()
        val done = task("done", TaskNoticeState.FINISHED)
        state.onEvent(done, 42, 1)
        state.onEvent(done, 42, 10_000)
        assertNull(state.current(1 + TaskCapsuleState.FLASH_MS))
    }

    @Test fun completionsQueueBehindApproval() {
        val state = TaskCapsuleState()
        state.onEvent(task("approval", TaskNoticeState.WAITING), 1, 1)
        state.onEvent(task("first", TaskNoticeState.FINISHED), 2, 2)
        state.onEvent(task("second", TaskNoticeState.FINISHED), 3, 3)
        assertEquals("approval", state.current(3)?.session)
        state.resolve("approval", 4)
        assertEquals("first", state.current(4)?.session)
        assertEquals("second", state.current(4 + TaskCapsuleState.FLASH_MS)?.session)
    }

    @Test fun failureRemainsUntilAcknowledgedOrTaskResumes() {
        val state = TaskCapsuleState()
        state.onEvent(task("failed", TaskNoticeState.FAILED), 1, 1)
        assertEquals(TaskNoticeState.FAILED, state.current(60_000)?.state)
        state.onSnapshot(emptyList(), 60_001, setOf("failed"), setOf("failed"))
        assertNull(state.current(60_001))
        state.onEvent(task("failed", TaskNoticeState.FAILED), 2, 60_002)
        state.resolve("failed", 60_003)
        assertNull(state.current(60_003))
    }

    @Test fun snapshotKeepsFullQuestionAndOptionsFromEvent() {
        val state = TaskCapsuleState()
        val question = CapsuleTask("s", "title", "Delete file?\n1. Yes\n2. No", TaskNoticeState.WAITING,
            prompt = "current-question", choices = listOf(TaskChoice("1", "Yes"), TaskChoice("2", "No")))
        state.onEvent(question, 1, 1)
        state.onSnapshot(listOf(task("s", TaskNoticeState.WAITING)), 2)
        assertEquals(question, state.current(2))
    }

    @Test fun nextQuestionAppearsImmediatelyAndOldResponseCannotClearIt() {
        val state = TaskCapsuleState()
        val first = CapsuleTask("s", "task", "first", TaskNoticeState.WAITING, prompt = "first")
        val next = first.copy(body = "next", prompt = "next")
        state.onEvent(first, 1, 1)
        state.resolve("s", 2, "first")
        state.onSnapshot(listOf(next), 3)
        assertEquals(next, state.current(3))
        state.resolve("s", 4, "first")
        assertEquals(next, state.current(4))
    }

    @Test fun completionRejectsOldSnapshotButAllowsNextQuestionImmediately() {
        val state = TaskCapsuleState()
        val old = CapsuleTask("s", "task", "old", TaskNoticeState.WAITING, prompt = "old")
        val next = old.copy(body = "next", prompt = "next")
        state.onEvent(old, 1, 1)
        state.onEvent(task("s", TaskNoticeState.FINISHED), 2, 2)
        state.onSnapshot(listOf(old), 3)
        assertEquals(TaskNoticeState.FINISHED, state.current(3)?.state)
        state.onSnapshot(listOf(next), 4)
        assertEquals(next, state.current(4))
    }

    @Test fun failureDoesNotResurrectAnsweredQuestionFromSnapshot() {
        val state = TaskCapsuleState()
        val old = CapsuleTask("s", "task", "old", TaskNoticeState.WAITING, prompt = "old")
        state.onEvent(old, 1, 1)
        state.onEvent(task("s", TaskNoticeState.FAILED), 2, 2)
        state.onSnapshot(listOf(old), 3)
        assertEquals(TaskNoticeState.FAILED, state.current(3)?.state)
        state.onSnapshot(listOf(old.copy(prompt = "next")), 4)
        assertEquals(TaskNoticeState.WAITING, state.current(4)?.state)
    }

    @Test fun firstQuestionAfterCompletionIsNotSuppressed() {
        val state = TaskCapsuleState()
        state.onEvent(task("s", TaskNoticeState.FINISHED), 1, 1)
        val question = CapsuleTask("s", "task", "new", TaskNoticeState.WAITING, prompt = "new")
        state.onSnapshot(listOf(question), 2)
        assertEquals(question, state.current(2))
    }
}
