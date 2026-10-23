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
    private var flash: CapsuleTask? = null
    private var flashUntil = 0L
    private val queued = ArrayDeque<CapsuleTask>()

    fun reset() {
        waiting.clear(); failed.clear(); resolved.clear(); resolvedPrompts.clear(); recentEvents.clear()
        flash = null; flashUntil = 0L; queued.clear()
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
                if (flash != null) flashUntil = 0L
            }
            TaskNoticeState.FAILED -> {
                resolve(task.session, now)
                failed[task.session] = task
                if (flash != null) flashUntil = 0L
            }
            TaskNoticeState.FINISHED -> {
                resolve(task.session, now)
                if (flash == null) {
                    flash = task
                    flashUntil = if (waiting.isEmpty() && failed.isEmpty()) now + FLASH_MS else 0L
                } else queued.addLast(task)
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
        queued.removeAll { it.session == session }
        if (flash?.session == session) { flash = null; flashUntil = 0L }
    }

    fun pending(now: Long): List<CapsuleTask> {
        current(now)
        return (waiting.values + failed.values + listOfNotNull(flash) + queued).distinctBy { it.session }
    }

    fun current(now: Long): CapsuleTask? {
        waiting.values.firstOrNull()?.let { return it }
        failed.values.firstOrNull()?.let { return it }
        if (flash != null && flashUntil == 0L) flashUntil = now + FLASH_MS
        if (now < flashUntil) return flash
        flash = null
        if (queued.isNotEmpty()) {
            flash = queued.removeFirst()
            flashUntil = now + FLASH_MS
            return flash
        }
        return null
    }

    fun nextChangeDelay(now: Long): Long? = if (waiting.isEmpty() && failed.isEmpty() && flash != null && now < flashUntil) flashUntil - now else null

    companion object {
        const val FLASH_MS = 15_000L
        private const val RESOLVED_MS = 30_000L
    }
}
