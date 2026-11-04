package com.roami.app

object TaskNoticeDelivery {
    fun postSeparate(session: String, capsule: CapsuleTask?): Boolean = capsule?.session != session

    fun retainHistory(previous: CapsuleTask?, current: CapsuleTask?, pending: List<CapsuleTask>): Boolean {
        if (previous == null || previous.session == current?.session) return false
        val latest = pending.firstOrNull { it.session == previous.session }
        if (latest != null) return latest == previous
        return previous.state == TaskNoticeState.FINISHED
    }
}
