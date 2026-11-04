package com.roami.app

enum class TaskAttention { COMPLETED, APPROVAL, CHOICE, MULTIPLE, INPUT, FAILED }

fun CapsuleTask.attention(): TaskAttention = when (state) {
    TaskNoticeState.FINISHED -> TaskAttention.COMPLETED
    TaskNoticeState.FAILED -> TaskAttention.FAILED
    TaskNoticeState.WAITING -> when {
        selectionMode == "multiple" || choices.any { Regex("^\\s*(?:\\[[ xX✓]\\]|[☐☑])").containsMatchIn(it.label) } -> TaskAttention.MULTIPLE
        choices.isEmpty() -> TaskAttention.INPUT
        choices.any { it.value == "yes" || Regex("(?i)^(yes|allow|approve|允许|同意|是)").containsMatchIn(it.label) } &&
            choices.any { it.value == "no" || Regex("(?i)^(no\\b|deny|reject|拒绝|否|不允许)").containsMatchIn(it.label) } -> TaskAttention.APPROVAL
        else -> TaskAttention.CHOICE
    }
}
