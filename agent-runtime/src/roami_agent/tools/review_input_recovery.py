"""Correct rejected review inputs without changing admission or granting authority."""

RECOVERY = {
    "SWARM_ARTIFACT_REVIEW_REQUIRED": (
        "Read each selected current-run text artifact with read artifact://ID (artifact_read), "
        "using its retained host ID. A filesystem file_read is not a retained-artifact read. "
        "Read all pages without truncation, then call swarm_verify in a later assistant message "
        "of this same Main turn. Keep the original task/revision/run and selected artifact IDs; "
        "do not substitute summaries, hashes, old-run artifacts or an empty artifactIds list."
    ),
    "SWARM_DELIVERABLE_EVIDENCE_REQUIRED": (
        "Inspect the current task's declared deliverables and retained result artifacts. "
        "Select nonempty current-run artifactIds that meet those requirements, read their full "
        "text with read artifact://ID, then verify. Missing evidence or binary/external-action "
        "review needs its supported host/UI path; do not remove requirements or claim success."
    ),
    "PUBLICATION_AUTHOR_NOT_CURRENT": (
        "Check the original member's current task/revision/run and completion state. "
        "The current artifact task must first pass swarm_verify; a waiting_user task is not "
        "accepted. Do not steer the author again before freezing the accepted content. "
        "This error is not an account or platform authorization result."
    ),
    "INVALID_PUBLICATION_MANIFEST": (
        "Use a manifest with nested identity {taskId, revision: integer, runId}, and files[] "
        "entries with that same identity plus path, positive bytes and full sha256. "
        "A flat top-level taskId/revision/runId is not identity. Paths are relative to the "
        "manifest file's directory: for publication-input/manifest.json and a sibling post.txt, "
        "declare post.txt, not publication-input/post.txt. Correct the manifest through its "
        "assigned author; do not bypass identity, hash or workspace checks."
    ),
    "PUBLICATION_CONTENT_USE_RELATIVE_MANIFEST_FILE_PATH": (
        "Use the exact manifest.files[].path for content.body and each content.images entry. "
        "These are file paths relative to the manifest's directory, not literal post text or "
        "project/run prefixes. Preserve the planned publication's businessKey when correcting."
    ),
    "PUBLICATION_ARTIFACT_NOT_CURRENT": (
        "Use a retained, non-provisional artifact from the original author's accepted current "
        "run. manifest.id is the host artifact ID, not a filename. Inspect the actual current "
        "task result before correcting; do not relabel old-run files or fabricate provenance."
    ),
}


def review_input_recovery(code):
    return RECOVERY.get(code)
