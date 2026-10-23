package com.roami.app

import org.junit.Assert.assertEquals
import org.junit.Test

class TaskAttentionTest {
    private fun waiting(choices: List<TaskChoice>, mode: String = "single") = CapsuleTask("s", "Task", "Question", TaskNoticeState.WAITING,
        choices = choices, selectionMode = mode)

    @Test fun distinguishesApprovalChoicesAndMissingInformation() {
        assertEquals(TaskAttention.APPROVAL, waiting(listOf(TaskChoice("yes", ""), TaskChoice("no", ""))).attention())
        assertEquals(TaskAttention.CHOICE, waiting(listOf(TaskChoice("1", "Local"), TaskChoice("2", "Staging"))).attention())
        assertEquals(TaskAttention.INPUT, waiting(emptyList()).attention())
    }

    @Test fun multipleSelectionCannotBecomeASingleShortcut() {
        assertEquals(TaskAttention.MULTIPLE, waiting(listOf(TaskChoice("1", "Yes"), TaskChoice("2", "No")), "multiple").attention())
    }

    @Test fun pendingListRetainsOtherTasksAfterOneIsResolved() {
        val state = TaskCapsuleState()
        state.onEvent(waiting(emptyList()).copy(session = "first"), 1, 1)
        state.onEvent(waiting(emptyList()).copy(session = "second"), 2, 2)
        state.onEvent(CapsuleTask("done", "Result", "Done", TaskNoticeState.FINISHED), 3, 3)
        assertEquals(listOf("first", "second", "done"), state.pending(3).map { it.session })
        state.resolve("first", 4)
        assertEquals(listOf("second", "done"), state.pending(4).map { it.session })
    }

    @Test fun newQuestionRemovesObsoleteCompletionForSameTask() {
        val state = TaskCapsuleState()
        state.onEvent(CapsuleTask("s", "Result", "Done", TaskNoticeState.FINISHED), 1, 1)
        state.onEvent(waiting(emptyList()), 2, 2)
        state.resolve("s", 3)
        assertEquals(emptyList<CapsuleTask>(), state.pending(3))
    }

    @Test fun taskIndexPreservesIdentityAndSelectionMode() {
        val tasks = listOf(waiting(listOf(TaskChoice("1", "ColorOS 16")), "multiple"))
        assertEquals(tasks, TaskNoticeIndex.decode(TaskNoticeIndex.encode(tasks)))
    }
}
