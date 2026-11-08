"""Match exact frozen UTF-8 text to the current Main's complete successful reads."""

import hashlib
import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows
from roami_agent.storage.publication_review_context import review_turn


def text_coverage(receipts, artifact):
    pages = {"bytes": {}, "lines": {}}
    for receipt in receipts:
        try:
            value = json.loads(json.loads(receipt["content_json"])["text"])
            if not isinstance(value, dict):
                continue
            reference = value.get("artifact")
            if (
                not isinstance(reference, dict)
                or reference.get("id") != artifact["id"]
                or reference.get("sha256") != artifact["sha256"]
                or value.get("textAvailable") is not True
                or not isinstance(value.get("text"), str)
                or value.get("truncated")
            ):
                continue
            body = value["text"].encode()
        except (ValueError, KeyError, TypeError, UnicodeError):
            continue
        unit = "lines" if "offsetLines" in value else "bytes"
        offset = value.get("offsetLines" if unit == "lines" else "offset")
        following = value.get("nextOffset")
        if type(offset) is not int or offset < (1 if unit == "lines" else 0):
            continue
        if unit == "bytes":
            if (
                type(following) is not int
                or following != offset + len(body)
                or following > artifact["size_bytes"]
            ):
                continue
            end = following == artifact["size_bytes"] and value.get("hasMore") is False
            if end:
                following = None
        else:
            if following is not None and (type(following) is not int or following <= offset):
                continue
            if following is None and value.get("hasMore", False) is not False:
                continue
        if not body and following is not None:
            continue
        pages[unit].setdefault(offset, []).append(
            (
                body,
                following,
                {"toolCallId": receipt["call_id"], "resultMessageId": receipt["result_id"]},
            )
        )
    for unit, available in pages.items():
        pending = [((1 if unit == "lines" else 0), hashlib.sha256(), 0, [])]
        visited = set()
        while pending:
            offset, digest, length, proof = pending.pop()
            state = (offset, length, digest.hexdigest())
            if state in visited:
                continue
            visited.add(state)
            for body, following, source in available.get(offset, []):
                updated = digest.copy()
                updated.update(body)
                size = length + len(body)
                if size > artifact["size_bytes"]:
                    continue
                reads = [*proof, source]
                if following is None:
                    if size == artifact["size_bytes"] and updated.hexdigest() == artifact["sha256"]:
                        return reads
                else:
                    pending.append((following, updated, size, reads))
    return None


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
