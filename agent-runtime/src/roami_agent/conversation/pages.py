"""Bounded Web history, with cursors validated against the selected branch lineage."""

import json

from roami_agent.conversation.okr_message_context import human_text
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows
from roami_agent.storage.reply_previews import public_preview_message
from roami_agent.storage.task_request import task_user_request
from roami_agent.storage.transcript_repository import owned


def lineage(db, cid, selected):
    segments, upper = [], None
    for _ in range(17):
        branch = row(db, "SELECT * FROM branches WHERE id=? AND conversation_id=?", (selected, cid))
        if not branch:
            raise DomainError("BRANCH_NOT_FOUND", 404)
        segments.append((selected, branch["head_seq"] if upper is None else upper))
        if not branch["parent_branch_id"]:
            return segments
        cut = row(db, "SELECT seq FROM messages WHERE id=?", (branch["fork_message_id"],))
        if not cut:
            raise DomainError("BRANCH_NOT_FOUND", 404)
        selected, upper = branch["parent_branch_id"], cut["seq"]
    raise DomainError("BRANCH_DEPTH_EXCEEDED")


def position(db, cid, segments, mid):
    value = row(
        db,
        "SELECT branch_id,seq,deleted_ms,status FROM messages WHERE id=? AND conversation_id=?",
        (mid, cid),
    )
    for index, (bid, upper) in enumerate(segments):
        if value and value["branch_id"] == bid and value["seq"] <= upper:
            return index, value
    raise DomainError("INVALID_MESSAGE_CURSOR")


def message_view(value, completed=None, *, compact=True):
    content = json.loads(value["content_json"])
    offset = len(content.get("text", ""))
    truncated = False
    if compact:
        context = content.get("okrContext")
        if value["role"] == "user":
            content["text"] = human_text(content)
            offset = len(content["text"])
        content = {
            k: v
            for k, v in content.items()
            if k
            in {
                "text",
                "question",
                "sessionReply",
                "taskStatus",
                "attachments",
                "tool_calls",
                "replyPreview",
            }
        }
        if isinstance(context, dict) and context.get("version") == 1:
            content["okrContext"] = {"version": 1, "revision": context["revision"]}
        if len(content.get("text", "")) > 2000:
            content["text"] = content["text"][:2000]
            truncated = True
        if content.get("tool_calls"):
            content["tool_calls"] = [{"id": call.get("id")} for call in content["tool_calls"]]
        if len(json.dumps(content, ensure_ascii=False).encode()) > (
            40_000 if content.get("replyPreview") else 12_000
        ):
            content = {
                "text": str(content.get("text") or "")[:2000],
                **({"okrContext": content["okrContext"]} if "okrContext" in content else {}),
            }
            truncated = True
    return {
        **{
            key: value[key]
            for key in ("id", "branch_id", "seq", "turn_id", "role", "status", "created_ms")
        },
        "content": content,
        "contentTruncated": truncated,
        "contentOffset": offset,
        "completedEventId": completed,
    }


def activity_summaries(db, cid, transcript):
    if not transcript:
        return []
    mids = [m["id"] for m in transcript]
    placeholders = ",".join("?" for _ in mids)
    facts = rows(
        db,
        "SELECT json_extract(json_remove(payload_json,'$.activity.preview','$.activity.routingDecision'),'$.activity') AS activity_json "
        "FROM events WHERE id IN (SELECT MAX(id) FROM events WHERE conversation_id=? "
        "AND json_type(payload_json,'$.activity')='object' "
        "AND json_extract(payload_json,'$.activity.anchorMessageId') IN ("
        + placeholders
        + ") GROUP BY json_extract(payload_json,'$.activity.id') ORDER BY MAX(id) DESC LIMIT 400) ORDER BY id DESC",
        (cid, *mids),
    )
    hidden = {
        "tool:" + item["id"]
        for item in rows(
            db,
            "SELECT c.id FROM tool_calls c JOIN messages m ON m.id=c.result_message_id "
            "WHERE (m.deleted_ms IS NOT NULL OR m.status='deleted') AND c.assistant_message_id IN ("
            + placeholders
            + ")",
            tuple(mids),
        )
    }
    latest = {}
    for fact in facts:
        item = json.loads(fact["activity_json"])
        if item["id"] not in hidden:
            latest.setdefault(item["id"], item)
    return sorted(latest.values(), key=lambda item: (item["startedMs"], item["id"]))


def conversation_page(db, owner, cid, branch=None, *, before=None, anchor=None, limit=50):
    conversation = owned(db, owner, cid)
    selected = branch or conversation["active_branch_id"]
    segments = lineage(db, cid, selected)
    index, upper = 0, segments[0][1]
    if before or anchor:
        index, cursor = position(db, cid, segments, before or anchor)
        if anchor and (
            cursor["deleted_ms"] is not None
            or cursor["status"] == "deleted"
            or row(
                db,
                "SELECT 1 AS omitted FROM context_omissions WHERE owner_id=? AND message_id=?",
                (owner, anchor),
            )
        ):
            raise DomainError("MESSAGE_NOT_FOUND", 404)
        upper = cursor["seq"] - 1 if before else min(segments[index][1], cursor["seq"] + limit // 2)
    selected_rows = []
    for segment_index in range(index, len(segments)):
        bid, bound = segments[segment_index]
        found = rows(
            db,
            "SELECT id,conversation_id,branch_id,seq,turn_id,role,status,created_ms,content_json FROM messages m "
            "WHERE branch_id=? AND seq<=? AND deleted_ms IS NULL AND status!='deleted' "
            "AND role IN ('user','assistant') AND NOT EXISTS(SELECT 1 FROM context_omissions o "
            "WHERE o.owner_id=? AND o.message_id=m.id) ORDER BY seq DESC LIMIT ?",
            (
                bid,
                upper if segment_index == index else bound,
                owner,
                limit + 1 - len(selected_rows),
            ),
        )
        selected_rows.extend(found)
        if len(selected_rows) > limit:
            break
    more = len(selected_rows) > limit
    selected_rows = list(reversed(selected_rows[:limit]))
    completed = (
        {
            item["message_id"]: item["id"]
            for item in rows(
                db,
                "SELECT id,message_id FROM events WHERE conversation_id=? AND kind='message.completed' "
                "AND message_id IN (" + ",".join("?" for _ in selected_rows) + ")",
                (cid, *(m["id"] for m in selected_rows)),
            )
        }
        if selected_rows
        else {}
    )
    scan_cursor = selected_rows[0]["id"] if selected_rows else None
    aliases, visible = {}, []
    for entry in selected_rows:
        if json.loads(entry["content_json"]).get("taskSteer"):
            source = task_user_request(db, entry, identity_only=True)
            if source and source["id"] != entry["id"]:
                try:
                    position(db, cid, segments, source["id"])
                except DomainError:
                    pass
                else:
                    aliases[entry["id"]] = source["id"]
                    continue
        visible.append(entry)
    messages = [
        message_view(public_preview_message(db, m), completed.get(m["id"])) for m in visible
    ]
    while len(json.dumps(messages, ensure_ascii=False).encode()) > 220000 and len(messages) > 1:
        messages.pop(0)
        visible.pop(0)
        scan_cursor = visible[0]["id"]
        more = True
    visible_ids = {m["id"] for m in visible}
    activities = activity_summaries(
        db,
        cid,
        [m for m in selected_rows if aliases.get(m["id"], m["id"]) in visible_ids],
    )
    for item in activities:
        item["anchorMessageId"] = aliases.get(item["anchorMessageId"], item["anchorMessageId"])
    compact = row(
        db,
        "SELECT id,payload_json FROM jobs WHERE kind='context.compact' "
        "AND json_extract(payload_json,'$.branchId')=? ORDER BY rowid DESC LIMIT 1",
        (selected,),
    )
    result = {
        "conversation": conversation,
        "branchId": selected,
        "messages": messages,
        "turns": rows(
            db,
            "SELECT id,state FROM turns WHERE branch_id=? ORDER BY created_ms DESC LIMIT 200",
            (selected,),
        ),
        "activities": [],
        "snapshotCursor": db.execute(
            "SELECT COALESCE(MAX(id),0) FROM events WHERE conversation_id=?", (cid,)
        ).fetchone()[0],
        "compaction": {"operationId": compact["id"], **json.loads(compact["payload_json"])}
        if compact
        else None,
        "page": {
            "hasMore": more,
            "olderCursor": scan_cursor if more else None,
        },
    }
    remaining = 256000 - len(json.dumps(result, ensure_ascii=False).encode())
    for item in sorted(activities, key=lambda item: (item["kind"] == "tool", -item["startedMs"])):
        size = len(json.dumps(item, ensure_ascii=False).encode()) + 1
        if size <= remaining:
            result["activities"].append(item)
            remaining -= size
    result["activities"].sort(key=lambda item: (item["startedMs"], item["id"]))
    return result


def message_detail(db, owner, cid, mid, branch=None):
    conversation = owned(db, owner, cid)
    position(db, cid, lineage(db, cid, branch or conversation["active_branch_id"]), mid)
    value = row(
        db,
        "SELECT id,conversation_id,branch_id,seq,turn_id,role,status,created_ms,content_json FROM messages m "
        "WHERE id=? AND deleted_ms IS NULL AND status!='deleted' AND NOT EXISTS "
        "(SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id)",
        (mid, owner),
    )
    if not value:
        raise DomainError("MESSAGE_NOT_FOUND", 404)
    return message_view(public_preview_message(db, value), compact=False)
