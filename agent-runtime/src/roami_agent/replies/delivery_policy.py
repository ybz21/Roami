"""Outcome-first delivery guidance for Main and task executors."""

DELIVERY_INSTRUCTIONS = (
    "Reply in the original user's language, not the executor report's language. Default to 1-3 short "
    "sentences: outcome, real deliverable links, essential checks or next action. Reuse downloadUrl "
    "unchanged; /api/ URLs are not filesystem paths. No repeated brief, tool narration, logs, internal "
    "IDs/flags, headings, emoji or boilerplate offers. Explain queued, pending acceptance, failed or "
    "unknown results plainly; never claim unfinished work is done or invent files. Keep detailed "
    "evidence in the task. Explicit requests for detail/full content override brevity; preserve "
    "deliverables and material limitations."
)
