package com.roami.app

data class CapsuleTask(val session: String, val title: String, val body: String,
                       val state: TaskNoticeState, val actions: List<String> = emptyList(),
                       val prompt: String = "", val choices: List<TaskChoice> = emptyList(),
                       val selectionMode: String = "single")

class TaskCapsuleState {
    private val waiting = linkedMapOf<String, CapsuleTask>()
    private val failed = linkedMapOf<String, CapsuleTask>()
    private val resolved = mutableMapOf<String, Long>()
    private val resolvedPrompts = mutableMapOf<String, String>()
    private val recentEvents = linkedSetOf<Long>()
    private val completions = linkedMapOf<String, CapsuleTask>()
    private val completionUntil = mutableMapOf<String, Long>()

    fun reset() {
        waiting.clear(); failed.clear(); resolved.clear(); resolvedPrompts.clear(); recentEvents.clear()
        completions.clear(); completionUntil.clear()
    }

    fun onEvent(task: CapsuleTask, eventId: Long, now: Long) {
        if (eventId > 0 && !recentEvents.add(eventId)) return
        while (recentEvents.size > 128) recentEvents.remove(recentEvents.first())
        clearCompletion(task.session)
        when (task.state) {
            TaskNoticeState.WAITING -> {
                failed.remove(task.session)
                resolved.remove(task.session)
                resolvedPrompts.remove(task.session)
                waiting[task.session] = task
            }
            TaskNoticeState.FAILED -> {
                resolve(task.session, now)
                failed[task.session] = task
            }
            TaskNoticeState.FINISHED -> {
                resolve(task.session, now)
                completions[task.session] = task
                completionUntil[task.session] = now + FLASH_MS
            }
        }
    }

    fun onSnapshot(waitingItems: List<CapsuleTask>, now: Long, running: Set<String> = emptySet(), live: Set<String>? = null) {
        failed.keys.removeAll { it in running || live != null && it !in live }
        resolved.entries.removeAll { now >= it.value }
        val seen = waitingItems.map { it.session }.toSet()
        waiting.keys.retainAll(seen)
        waitingItems.forEach { task ->
            if (task.prompt.isNotBlank() && resolvedPrompts[task.session]?.let { it != task.prompt } == true) {
                resolved.remove(task.session)
                resolvedPrompts.remove(task.session)
            }
            if (task.session !in resolved) {
                if (task.prompt.isNotBlank()) waiting[task.session] = task else waiting.putIfAbsent(task.session, task)
            }
        }
    }

    fun resolve(session: String, now: Long, prompt: String? = null) {
        val current = waiting[session]
        if (prompt != null && current != null && current.prompt.isNotBlank() && current.prompt != prompt) return
        resolvedPrompts[session] = prompt ?: current?.prompt ?: ""
        waiting.remove(session)
        failed.remove(session)
        resolved[session] = now + RESOLVED_MS
    }

    fun acknowledgeFailure(session: String) { failed.remove(session) }

    private fun clearCompletion(session: String) {
        completions.remove(session)
        completionUntil.remove(session)
    }

    fun pending(now: Long): List<CapsuleTask> {
        current(now)
        return (waiting.values + failed.values + completions.values.reversed()).distinctBy { it.session }
    }

    fun current(now: Long): CapsuleTask? {
        completionUntil.filterValues { now >= it }.keys.toList().forEach(::clearCompletion)
        return waiting.values.firstOrNull() ?: failed.values.firstOrNull() ?: completions.values.lastOrNull()
    }

    fun nextChangeDelay(now: Long): Long? = completionUntil.values.minOrNull()?.let { (it - now).coerceAtLeast(1L) }

    companion object {
        const val FLASH_MS = 15_000L
        private const val RESOLVED_MS = 30_000L
    }
}
