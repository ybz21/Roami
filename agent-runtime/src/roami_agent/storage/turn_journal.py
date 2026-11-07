"""Transactional assistant messages, streaming deltas and turn outcomes."""

import json

from roami_agent.context.task_evidence import completion_for_reply
from roami_agent.protocol.errors import DomainError, public_error_code
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.replies.artifact_links import deliverable_links
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import event, row, rows
from roami_agent.storage.reply_previews import assert_preview_current, clear_reply_previews
from roami_agent.storage.swarm_coordination import origin as coordination_origin
from roami_agent.storage.transcript_repository import message


def completion_artifacts(db, turn, completion):
    references = completion_for_reply(completion or {}).get("result", {}).get("artifactRefs", [])
    if not isinstance(references, list):
        return []
    identifiers = [
        item["id"]
        for item in references[:4]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    if not identifiers:
        return []
    retained = rows(
        db,
        "SELECT id,name FROM artifacts WHERE owner_id=? AND task_id=? "
        "AND deleted_ms IS NULL AND id IN (" + ",".join("?" for _ in identifiers) + ")",
        (turn["owner_id"], completion["taskId"], *identifiers),
    )
    by_id = {item["id"]: item for item in retained}
    return [by_id[aid] for aid in dict.fromkeys(identifiers) if aid in by_id]


class TurnJournal:
    def __init__(self, database):
        self.db = database

    async def attempt_offset(self, turn):
        return await self.db.call(
            lambda db: db.execute(
                "SELECT COALESCE(MAX(attempt_no),0) FROM prompt_manifests WHERE turn_id=?",
                (turn["id"],),
            ).fetchone()[0]
        )

    async def defer(self, turn, *, only_if_pending=False):
        def write(db):
            assert_context_admitted(db, turn)
            if only_if_pending and not row(
                db,
                "SELECT u.id FROM turns u JOIN jobs j ON j.aggregate_id=u.id AND j.kind='turn.run' "
                "WHERE u.branch_id=? AND u.id!=? AND u.state='queued' AND u.trigger_kind='user' "
                "AND COALESCE(json_extract(j.payload_json,'$.deferred'),0)=0 LIMIT 1",
                (turn["branch_id"], turn["id"]),
            ):
                return False
            job = row(
                db,
                "SELECT id FROM jobs WHERE kind='turn.run' AND aggregate_id=? AND state='running'",
                (turn["id"],),
            )
            if not job or not row(
                db, "SELECT id FROM turns WHERE id=? AND state='running'", (turn["id"],)
            ):
                return False
            db.execute(
                "UPDATE messages SET status='interrupted' WHERE turn_id=? AND status='streaming'",
                (turn["id"],),
            )
            clear_reply_previews(db, turn["id"])
            db.execute("UPDATE turns SET state='queued' WHERE id=?", (turn["id"],))
            db.execute(
                "UPDATE jobs SET state='queued',payload_json=json_set(payload_json,'$.deferred',1) WHERE id=?",
                (job["id"],),
            )
            event(
                db,
                turn["conversation_id"],
                "turn.deferred",
                {"turnId": turn["id"], "reason": "NEW_USER_INTENT"},
                turn_id=turn["id"],
            )
            return True

        try:
            return await self.db.call(write, write=True)
        except DomainError:
            return False

    async def origin(self, turn):
        if turn.get("trigger_kind") == "continuation":
            delegated = await self.db.call(lambda db: coordination_origin(db, turn))
            if delegated:
                return delegated
        if turn.get("trigger_kind") == "completion":
            origin = await self.db.call(
                lambda db: row(
                    db,
                    "SELECT m.id,json_extract(native_content(m.content_json),'$.text') AS text FROM jobs j JOIN tasks t "
                    "ON t.id=json_extract(j.payload_json,'$.completion.taskId') "
                    "JOIN messages m ON m.id=t.origin_message_id "
                    "WHERE j.aggregate_id=? AND j.kind='turn.run' AND t.owner_id=? "
                    "AND t.origin_branch_id=? AND m.deleted_ms IS NULL "
                    "AND t.revision=json_extract(j.payload_json,'$.completion.taskRevision') "
                    "AND NOT EXISTS(SELECT 1 FROM context_omissions o "
                    "WHERE o.owner_id=t.owner_id AND o.message_id=m.id)",
                    (turn["id"], turn["owner_id"], turn["branch_id"]),
                )
            )
            if not origin:
                raise DomainError("CONTEXT_SOURCE_FORGOTTEN", 409)
            return origin
        return await self.db.call(
            lambda db: row(
                db,
                "SELECT id,json_extract(native_content(content_json),'$.text') AS text FROM messages WHERE turn_id=? AND role='user' AND deleted_ms IS NULL ORDER BY seq LIMIT 1",
                (turn["id"],),
            )
        )

    async def start(self, turn):
        def write(db):
            assert_context_admitted(db, turn)
            clear_reply_previews(db, turn["id"])
            mid = message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "assistant",
                {"text": ""},
                turn_id=turn["id"],
                status="streaming",
            )
            event(
                db,
                turn["conversation_id"],
                "message.started",
                {"messageId": mid, "turnId": turn["id"]},
                turn_id=turn["id"],
                message_id=mid,
            )
            return mid

        return await self.db.call(write, write=True)

    async def delta(self, turn, mid, text, delta):
        def write(db):
            assert_context_admitted(db, turn)
            db.execute(
                "UPDATE messages SET content_json=? WHERE id=?", (encoded({"text": text}), mid)
            )
            event(
                db,
                turn["conversation_id"],
                "message.delta",
                {
                    "messageId": mid,
                    "turnId": turn["id"],
                    "offset": len(text) - len(delta),
                    "text": delta,
                },
                turn_id=turn["id"],
                message_id=mid,
            )

        await self.db.call(write, write=True)

    async def preview(self, turn, mid, text, state="generating", *, clipped=False):
        def write(db):
            assert_context_admitted(db, turn)
            epoch = assert_preview_current(db, turn, mid, clearing=text is None)
            current = row(db, "SELECT content_json FROM messages WHERE id=?", (mid,))
            content = json.loads(current["content_json"])
            previous = content.get("replyPreview")
            if text is None:
                if not previous:
                    return
                content.pop("replyPreview")
                payload = {"messageId": mid, "turnId": turn["id"], "clear": True}
            else:
                value = {"text": text, "state": state, "clipped": clipped, "leaseEpoch": epoch}
                if previous == value:
                    return
                old = previous.get("text", "") if previous else ""
                reset = not text.startswith(old)
                offset = 0 if reset else len(old)
                content["replyPreview"] = value
                payload = {
                    "messageId": mid,
                    "turnId": turn["id"],
                    "offset": offset,
                    "text": text[offset:],
                    "state": state,
                    "clipped": clipped,
                    "reset": reset,
                }
            db.execute("UPDATE messages SET content_json=? WHERE id=?", (encoded(content), mid))
            event(
                db,
                turn["conversation_id"],
                "reply.preview",
                payload,
                turn_id=turn["id"],
                message_id=mid,
            )

        await self.db.call(write, write=True)

    async def finish(
        self, turn, mid, text, calls, usage, attempt, *, final, completion, question=None
    ):
        def write(db):
            assert_context_admitted(db, turn)
            delivery = text
            if final:
                delivery = deliverable_links(text, completion_artifacts(db, turn, completion))
            previous = row(db, "SELECT content_json FROM messages WHERE id=?", (mid,))
            preview = json.loads(previous["content_json"]).get("replyPreview") if previous else None
            content = {"text": delivery, **({"tool_calls": calls} if calls else {})}
            if (
                preview
                and not final
                and len(calls) == 1
                and calls[0].get("function", {}).get("name") == "reply"
            ):
                content["replyPreview"] = preview
            if question:
                content["question"] = question
            if completion:
                content["source"] = "task"
                if final:
                    content["answerText"] = text
            db.execute(
                "UPDATE messages SET content_json=?,status='completed' WHERE id=?",
                (encoded(content), mid),
            )
            db.execute(
                "UPDATE prompt_manifests SET usage_json=?,parts_json=json_set(parts_json,'$.responseMessageId',?) WHERE turn_id=? AND attempt_no=?",
                (encoded(usage) if usage else None, mid, turn["id"], attempt),
            )
            if final:
                db.execute(
                    "UPDATE turns SET state='completed',finished_ms=? WHERE id=?",
                    (now_ms(), turn["id"]),
                )
                cursor = event(
                    db,
                    turn["conversation_id"],
                    "message.completed",
                    {
                        "messageId": mid,
                        "turnId": turn["id"],
                        "source": "task" if completion else "main",
                        **({"question": question} if question else {}),
                        **(
                            {
                                "taskId": completion.get("taskId"),
                                "taskRevision": completion.get("taskRevision"),
                                "taskState": completion.get("state"),
                            }
                            if completion
                            else {}
                        ),
                    },
                    turn_id=turn["id"],
                    message_id=mid,
                )
                for binding in rows(
                    db,
                    "SELECT id,json_extract(route_json,'$.kind') AS kind FROM channel_bindings WHERE conversation_id=? AND enabled=1",
                    (turn["conversation_id"],),
                ):
                    if binding["kind"] == "app" and not completion:
                        continue
                    category = (
                        "decision"
                        if completion and completion.get("state") == "waiting_user"
                        else "task_result"
                    )
                    db.execute(
                        "INSERT INTO deliveries(id,event_id,channel_id,state,category) VALUES(?,?,?,'pending',?)",
                        (
                            identity(),
                            cursor,
                            binding["id"],
                            category if binding["kind"] == "app" else None,
                        ),
                    )
            else:
                event(
                    db,
                    turn["conversation_id"],
                    "message.tool_calls",
                    {"messageId": mid, "calls": calls},
                    turn_id=turn["id"],
                    message_id=mid,
                )

        await self.db.call(write, write=True)

    async def fail(self, turn, state, code, *, completion=None):
        def write(db):
            current = row(db, "SELECT lease_epoch FROM turns WHERE id=?", (turn["id"],))
            if not current or current["lease_epoch"] != turn.get(
                "lease_epoch", current["lease_epoch"]
            ):
                return
            clear_reply_previews(db, turn["id"])
            db.execute(
                "UPDATE turns SET state=?,finished_ms=? WHERE id=? AND state='running'",
                (state, now_ms(), turn["id"]),
            )
            db.execute(
                "UPDATE messages SET status=? WHERE turn_id=? AND status='streaming'",
                (state, turn["id"]),
            )
            event(
                db,
                turn["conversation_id"],
                "turn." + state,
                {"turnId": turn["id"], "error": code},
                turn_id=turn["id"],
            )
            if not completion or state == "interrupted":
                return
            task = row(
                db,
                "SELECT * FROM tasks WHERE id=? AND owner_id=?",
                (completion.get("taskId"), turn["owner_id"]),
            )
            if (
                not task
                or task["revision"] != completion.get("taskRevision", 1)
                or task["state"] != completion.get("state")
                or task["origin_branch_id"] != turn["branch_id"]
                or row(
                    db,
                    "SELECT 1 FROM context_omissions WHERE owner_id=? AND message_id=?",
                    (turn["owner_id"], task["origin_message_id"]),
                )
                or row(
                    db,
                    "SELECT 1 FROM events WHERE event_key=?",
                    ("completion.fallback:" + turn["id"],),
                )
            ):
                return
            fact = {
                "taskId": task["id"],
                "state": task["state"],
                "reportError": public_error_code(code),
                "errorCode": public_error_code(completion.get("result", {}).get("summary")),
            }
            content = {"source": "task", "taskStatus": fact}
            artifacts = completion_artifacts(db, turn, completion)
            if artifacts:
                content["text"] = deliverable_links("", artifacts).lstrip("\n")
            mid = message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "assistant",
                content,
                turn_id=turn["id"],
            )
            event(
                db,
                turn["conversation_id"],
                "message.completed",
                {
                    "messageId": mid,
                    "source": "task",
                    "taskId": task["id"],
                    "taskRevision": task["revision"],
                    "taskState": task["state"],
                },
                key="completion.fallback:" + turn["id"],
                message_id=mid,
            )

        await self.db.call(write, write=True)
