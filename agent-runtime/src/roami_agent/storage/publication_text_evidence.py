"""Match exact frozen UTF-8 text to the current Main's complete successful reads."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.artifact_text_coverage import text_coverage
from roami_agent.storage.database import row, rows
from roami_agent.storage.publication_review_context import review_turn


def reviewed_text(db, binding, required, *, prompt=None):
    turn = review_turn(db, binding)
    if not required:
        raise DomainError("PUBLICATION_TEXT_REQUIRED", 409)
    result = []
    for item in required:
        artifact = row(
            db,
            "SELECT * FROM artifacts WHERE id=? AND owner_id=? AND sha256=? AND size_bytes>0 "
            "AND (mime_type LIKE 'text/%' OR mime_type='application/json') "
            "AND deleted_ms IS NULL AND purged_ms IS NULL "
            "AND NOT EXISTS(SELECT 1 FROM memory_tombstones f WHERE f.owner_id=artifacts.owner_id "
            "AND f.source_fingerprint=artifacts.sha256)",
            (item["id"], binding["owner"], item["sha256"]),
        )
        if not artifact:
            raise DomainError("PUBLICATION_TEXT_UNAVAILABLE", 409)
        receipts = rows(
            db,
            "SELECT x.id AS call_id,m.id AS result_id,m.content_json FROM tool_calls x "
            "JOIN messages m ON m.id=x.result_message_id JOIN messages current ON current.id=? "
            "WHERE x.turn_id=? AND x.tool_name='artifact_read' AND x.state='succeeded' "
            "AND json_extract(x.arguments_json,'$.id')=? AND m.turn_id=x.turn_id "
            "AND m.role='tool' AND m.status='completed' AND m.deleted_ms IS NULL "
            "AND m.conversation_id=? AND m.branch_id=? AND m.seq<current.seq "
            "AND x.assistant_message_id!=current.id ORDER BY m.seq",
            (
                binding["assistantMessageId"],
                turn["id"],
                artifact["id"],
                binding["conversation"],
                turn["branch_id"],
            ),
        )
        if prompt is not None:
            receipts = [
                receipt
                for receipt in receipts
                if any(
                    message.get("role") == "tool"
                    and message.get("tool_call_id")
                    == json.loads(receipt["content_json"])["tool_call_id"]
                    and message.get("content") == json.loads(receipt["content_json"])["text"]
                    for message in prompt
                )
            ]
        proof = text_coverage(receipts, artifact)
        if proof is None:
            raise DomainError("PUBLICATION_TEXT_NOT_REVIEWED", 409)
        result.append(
            {
                "artifactId": artifact["id"],
                "sha256": artifact["sha256"],
                "sizeBytes": artifact["size_bytes"],
                "reads": proof,
            }
        )
    return result
