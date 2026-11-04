package com.roami.app

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TaskNoticeDeliveryTest {
    private fun task(name: String, state: TaskNoticeState = TaskNoticeState.FINISHED) = CapsuleTask(name, name, "结果", state)

    @Test fun promotedTaskDoesNotAlsoPostAnOrdinaryNotification() {
        val current = task("one")
        assertFalse(TaskNoticeDelivery.postSeparate("one", current))
        assertTrue(TaskNoticeDelivery.postSeparate("two", current))
        assertTrue(TaskNoticeDelivery.postSeparate("one", null))
    }

    @Test fun completionBecomesHistoryOnlyAfterItsCapsuleLeaves() {
        val done = task("one")
        assertFalse(TaskNoticeDelivery.retainHistory(done, done, listOf(done)))
        assertTrue(TaskNoticeDelivery.retainHistory(done, null, emptyList()))
        assertTrue(TaskNoticeDelivery.retainHistory(done, task("two"), listOf(done)))
    }

    @Test fun answeredQuestionsAndAcknowledgedErrorsDoNotReappearInHistory() {
        assertFalse(TaskNoticeDelivery.retainHistory(task("one", TaskNoticeState.WAITING), null, emptyList()))
        assertFalse(TaskNoticeDelivery.retainHistory(task("one", TaskNoticeState.FAILED), null, emptyList()))
    }

    @Test fun queuedQuestionIsKeptButAnOldCompletionCannotOverwriteANewQuestion() {
        val waiting = task("one", TaskNoticeState.WAITING)
        assertTrue(TaskNoticeDelivery.retainHistory(waiting, task("two"), listOf(waiting)))
        assertFalse(TaskNoticeDelivery.retainHistory(task("one"), task("two"), listOf(waiting)))
        assertFalse(TaskNoticeDelivery.retainHistory(null, null, emptyList()))
    }
}
