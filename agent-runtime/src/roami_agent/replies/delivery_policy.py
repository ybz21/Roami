"""Outcome-first delivery guidance for Main and task executors."""

COMPLETION_REPORT_INSTRUCTIONS = (
    "Completion callbacks report actual outcomes and essential findings, with file links and pending "
    "acceptance or blockers; file links alone are not a summary. "
    "Never substitute task_reply or task_queue_reply status text. "
)

DELIVERY_INSTRUCTIONS = (
    "Use the original user's language. Default to 1-3 short sentences: outcome, real links, essential "
    "checks or next action. Reuse downloadUrl unchanged; /api/ URLs are not filesystem paths. No "
    "repeated brief, tool narration, logs, IDs/flags, headings, emoji or boilerplate. State queued, "
    "pending acceptance, failed or unknown results plainly; never invent files or claim unfinished "
    "work done. Keep evidence in task details. Explicit detail/full-content requests override brevity; "
    "preserve deliverables and limitations. Structured outputs use specified fields/types only unless "
    "extensions are allowed; put extras in reports."
)
