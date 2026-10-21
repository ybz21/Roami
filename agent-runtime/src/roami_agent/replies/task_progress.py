"""Render an explicitly selected progress answer from authoritative task state."""


def request_language(text, fallback, quote=None):
    if quote and quote in text:
        return fallback
    if any("\u3400" <= char <= "\u9fff" for char in text):
        return "zh"
    if any(char.isascii() and char.isalpha() for char in text):
        return "en"
    return fallback


def task_progress(tasks, language, *, single):
    if tasks:
        language = tasks[0].get("replyLanguage", language)
    english = language == "en"
    if (single and not tasks) or any(t.get("contextExcluded") for t in tasks):
        return "The task status is unavailable." if english else "暂时查不到任务状态。"
    if not single:
        running = sum(
            t["state"] in {"preparing", "queued", "running", "cancelling", "verifying"}
            for t in tasks
        )
        waiting = sum(t["state"] == "waiting_user" for t in tasks)
        unresolved = sum(
            t["state"] == "interrupted"
            and (t.get("latestAttempt") or {}).get("stopConfirmed") is not True
            for t in tasks
        )
        if running:
            return (
                f"{running} task(s) are still in progress."
                if english
                else f"还有 {running} 个任务未结束。"
            )
        if unresolved:
            return (
                f"Execution has not been confirmed stopped for {unresolved} task(s)."
                if english
                else f"还有 {unresolved} 个任务尚未确认停止。"
            )
        if waiting:
            return (
                f"No tasks are running; {waiting} await your response."
                if english
                else f"没有正在运行的任务，{waiting} 个任务等待你回复。"
            )
        return "No tasks are running." if english else "没有正在运行的任务。"
    descriptions = {
        "succeeded": ("任务已完成。", "The task is complete."),
        "queued": ("任务还在排队。", "The task is still queued."),
        "preparing": ("任务正在准备。", "The task is being prepared."),
        "running": ("任务还在进行。", "The task is still running."),
        "verifying": ("任务正在核验结果。", "The result is being verified."),
        "cancelling": (
            "任务正在停止，尚未确认结束。",
            "The task is stopping; completion is unconfirmed.",
        ),
        "waiting_user": ("任务等待你回复或验收。", "The task awaits your response or acceptance."),
        "failed": ("任务失败。", "The task failed."),
        "cancelled": ("任务已取消。", "The task was cancelled."),
        "interrupted": (
            "任务已中断，结果尚未确认。",
            "The task was interrupted; the result is unconfirmed.",
        ),
    }
    return descriptions.get(
        tasks[0]["state"], ("任务结果尚未确认。", "The result is unconfirmed.")
    )[english]
