"""Transactional assistant messages, streaming deltas and turn outcomes."""

from roami_agent.protocol.errors import public_error_code
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import event, row, rows
from roami_agent.storage.transcript_repository import message


class TurnJournal:
    def __init__(self, database):
        self.db = database

    async def origin(self, turn):
        return await self.db.call(
            lambda db: row(
                db,
                "SELECT id FROM messages WHERE turn_id=? AND role='user' ORDER BY seq LIMIT 1",
                (turn["id"],),
            )
        )

    async def start(self, turn):
        def write(db):
            assert_context_admitted(db, turn)
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

    async def finish(self, turn, mid, text, calls, usage, attempt, *, final, completion):
        def write(db):
            assert_context_admitted(db, turn)
            content = {"text": text, **({"tool_calls": calls} if calls else {})}
            if completion:
                content["source"] = "task"
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
            mid = message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "assistant",
                {"source": "task", "taskStatus": fact},
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
