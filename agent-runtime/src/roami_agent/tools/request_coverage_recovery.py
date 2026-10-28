"""Describe coverage correction using only the current operation's accepted fields."""


def request_coverage_recovery(operation):
    scope = (
        "requestCoverage[].quote must be copied exactly from the current user message, "
        "including punctuation, paths and backticks; do not paraphrase. "
        "List independent outcomes; a deliverable's format, output path and acceptance checks "
        "are constraints of that outcome, not extra assignments. "
        "Keep prior quotes and actual accepted taskIds; do not repeat accepted work or drop pending repairs. "
    )
    if operation in {"delegate", "task_steer"}:
        scope += (
            "Exactly one requestCoverage entry has status=current for this handoff; keep other outcomes pending. "
            "Use requestComplete=false while another independent part remains. "
        )
        if operation == "task_steer":
            scope += (
                "If task_steer.sourceQuote is supplied, it must equal that current entry's quote. "
            )
    elif operation in {"reply", "task_reply", "task_queue_reply"}:
        scope += "A final reply must have no pending or current entries; deliver or hand off remaining outcomes first. "
    else:
        scope += "For a handoff keep exactly one current outcome; a final reply must have no pending or current outcomes. "
    return (
        scope
        + "Use only fields in this operation's schema; no task has started from this rejected call."
    )
