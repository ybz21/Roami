"""Correlate legacy session delivery with explicit, durable executor reports."""

import hashlib
import json
import os
import shlex
import shutil

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.http import SessionReport
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.replies.notifications import Notifications
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row, rows
from roami_agent.storage.transcript_repository import owned


class SessionDispatches:
    def __init__(self, database, settings):
        self.db, self.settings = database, settings

    def reply_command(self, dispatch_id):
        argv = []
        if self.db.instance_paths:
            names = {
                "homeRoot": "ROAMI_HOME",
                "dataRoot": "ROAMI_DATA",
                "databaseRoot": "ROAMI_DATABASE_DIR",
                "backupRoot": "ROAMI_BACKUP_DIR",
            }
            argv = ["env"] + [
                name + "=" + self.db.instance_paths[key] for key, name in names.items()
            ]
            argv += ["ROAMI_CONFIG=" + self.db.instance_paths["homeRoot"] + "/config.yaml"]
            if os.environ.get("XDG_RUNTIME_DIR"):
                argv += ["XDG_RUNTIME_DIR=" + os.environ["XDG_RUNTIME_DIR"]]
        argv += [
            shutil.which(self.settings.cli_bin) or self.settings.cli_bin,
            "agent",
            "reply",
            "--dispatch",
            dispatch_id,
            "--file",
            "RESULT.json",
        ]
        return shlex.join(argv)

    async def prepare(self, session_id, text, key, binding):
        digest = hashlib.sha256(encoded([session_id, text]).encode()).hexdigest()

        def write(db):
            owner, cid = binding["owner"], binding["conversation"]
            owned(db, owner, cid)
            turn = row(
                db, "SELECT * FROM turns WHERE id=? AND conversation_id=?", (binding["turnId"], cid)
            )
            origin = row(
                db,
                "SELECT * FROM messages WHERE id=? AND conversation_id=? AND deleted_ms IS NULL",
                (binding.get("originMessageId"), cid),
            )
            if not turn or not origin:
                raise DomainError("SESSION_DISPATCH_ORIGIN_REQUIRED", 409)
            assert_context_admitted(db, {**turn, "owner_id": owner})
            if row(
                db,
                "SELECT 1 FROM context_omissions WHERE owner_id=? AND message_id=?",
                (owner, origin["id"]),
            ):
                raise DomainError("CONTEXT_SOURCE_FORGOTTEN", 409)
            old = row(
                db,
                "SELECT * FROM session_dispatches WHERE owner_id=? AND request_key=?",
                (owner, key),
            )
            if old:
                if old["request_digest"] != digest or old["turn_id"] != turn["id"]:
                    raise DomainError("MESSAGE_KEY_CONFLICT", 409)
                return old
            did = identity()
            prompt = text + (
                "\n\n[Roami task return channel]\n"
                "This request was dispatched from the user's Main conversation. Before your final reply, "
                "report the actual result to Main using this local CLI; replying only in this session does not notify Main. "
                "Write a UTF-8 JSON result file, then run:\n"
                + self.reply_command(did)
                + "\nReplace RESULT.json with the file you wrote. Format: "
                '{"key":"final","status":"completed","summary":"Concise result in the user language, actual links/files, checks and limits"}. '
                "Use status=failed on failure; never report completed for unfinished work. "
                "For progress or a blocker, use a distinct stable key and status=progress or blocked; "
                "blocked may include question={prompt,options:[{label,description}]} with 2-4 real choices. "
                "A completed/failed report is final. Retry a failed callback with the SAME key and identical JSON; "
                "do not rerun the work just because its report failed. Include no credentials. "
                "If the CLI fails, retain the result file and state that Main has not acknowledged it.\n"
            )
            if len(prompt.encode()) > 100000:
                raise DomainError("INVALID_SESSION_MESSAGE")
            db.execute(
                "INSERT INTO session_dispatches(id,owner_id,request_key,request_digest,conversation_id,branch_id,turn_id,origin_message_id,session_id,prompt,created_ms,updated_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    did,
                    owner,
                    key,
                    digest,
                    cid,
                    turn["branch_id"],
                    turn["id"],
                    origin["id"],
                    session_id,
                    prompt,
                    now_ms(),
                    now_ms(),
                ),
            )
            return row(db, "SELECT * FROM session_dispatches WHERE id=?", (did,))

        return await self.db.call(write, write=True)

    async def record_delivery(self, dispatch, receipt=None, *, error_code=None):
        def write(db):
            db.execute(
                "UPDATE session_dispatches SET delivery_state=?,delivery_receipt_json=?,session_id=?,updated_ms=? WHERE id=?",
                (
                    "failed" if error_code else "delivered" if receipt else "unknown",
                    encoded({"errorCode": error_code})
                    if error_code
                    else encoded(receipt)
                    if receipt
                    else None,
                    receipt["sessionId"] if receipt else dispatch["session_id"],
                    now_ms(),
                    dispatch["id"],
                ),
            )

        await self.db.call(write, write=True)

    async def report(self, owner, dispatch_id, result):
        result = SessionReport.model_validate(result).model_dump(exclude_none=True)

        def write(db):
            dispatch = row(
                db,
                "SELECT * FROM session_dispatches WHERE id=? AND owner_id=?",
                (dispatch_id, owner),
            )
            if not dispatch:
                raise DomainError("SESSION_DISPATCH_NOT_FOUND", 404)
            owned(db, owner, dispatch["conversation_id"])
            try:
                assert_context_admitted(db, {"id": dispatch["turn_id"], "owner_id": owner})
            except DomainError as exc:
                # Stopping Main intake does not cancel independently dispatched work.
                if exc.code != "TURN_INTERRUPTED":
                    raise
            if row(
                db,
                "SELECT 1 FROM context_omissions WHERE owner_id=? AND message_id=?",
                (owner, dispatch["origin_message_id"]),
            ):
                raise DomainError("CONTEXT_SOURCE_FORGOTTEN", 409)
            prior = row(
                db,
                "SELECT * FROM session_dispatch_reports WHERE dispatch_id=? AND report_key=?",
                (dispatch_id, result["key"]),
            )
            if prior:
                if prior["result_json"] != encoded(result):
                    raise DomainError("SESSION_REPORT_KEY_CONFLICT", 409)
                return {**json.loads(prior["receipt_json"]), "reused": True}
            if dispatch["final_status"]:
                raise DomainError("SESSION_DISPATCH_ALREADY_REPORTED", 409)
            if dispatch["delivery_state"] == "failed":
                raise DomainError("SESSION_DISPATCH_NOT_DELIVERED", 409)
            metadata = {
                "dispatchId": dispatch_id,
                "sessionId": dispatch["session_id"],
                "status": result["status"],
                "verified": False,
            }
            receipt = Notifications.publish_in_transaction(
                db,
                owner,
                dispatch["conversation_id"],
                result["summary"],
                source="task_result",
                dedupe_key="session:" + dispatch_id + ":" + result["key"],
                branch_id=dispatch["branch_id"],
                priority="attention" if result["status"] in {"failed", "blocked"} else "normal",
            )
            mid = receipt["messageId"]
            content = json.loads(
                row(db, "SELECT content_json FROM messages WHERE id=?", (mid,))["content_json"]
            )
            content["sessionReply"] = metadata
            content["sourceMessageIds"] = [dispatch["origin_message_id"]]
            if result.get("question"):
                content["question"] = result["question"]
            db.execute(
                "UPDATE messages SET content_json=?,reply_to_id=? WHERE id=?",
                (encoded(content), dispatch["origin_message_id"], mid),
            )
            payload = json.loads(
                row(db, "SELECT payload_json FROM events WHERE id=?", (receipt["eventId"],))[
                    "payload_json"
                ]
            )
            db.execute(
                "UPDATE events SET payload_json=? WHERE id=?",
                (
                    encoded(
                        {**payload, "sessionReply": metadata, "sourceTurnId": dispatch["turn_id"]}
                    ),
                    receipt["eventId"],
                ),
            )
            receipt = {**receipt, **metadata}
            db.execute(
                "INSERT INTO session_dispatch_reports VALUES(?,?,?,?,?)",
                (dispatch_id, result["key"], encoded(result), encoded(receipt), now_ms()),
            )
            db.execute(
                "UPDATE session_dispatches SET final_status=?,updated_ms=? WHERE id=?",
                (
                    result["status"] if result["status"] in {"completed", "failed"} else None,
                    now_ms(),
                    dispatch_id,
                ),
            )
            return receipt

        return await self.db.call(write, write=True)

    async def status(self, owner, cid, dispatch_id):
        def read(db):
            owned(db, owner, cid)
            item = row(
                db,
                "SELECT * FROM session_dispatches WHERE id=? AND owner_id=? AND conversation_id=?",
                (dispatch_id, owner, cid),
            )
            if not item:
                raise DomainError("SESSION_DISPATCH_NOT_FOUND", 404)
            if row(
                db,
                "SELECT 1 FROM context_omissions WHERE owner_id=? AND message_id=?",
                (owner, item["origin_message_id"]),
            ):
                raise DomainError("CONTEXT_SOURCE_FORGOTTEN", 409)
            reports = rows(
                db,
                "SELECT result_json,created_ms FROM session_dispatch_reports WHERE dispatch_id=? ORDER BY rowid DESC LIMIT 5",
                (dispatch_id,),
            )
            reports.reverse()
            return {
                "dispatchId": item["id"],
                "sessionId": item["session_id"],
                "delivery": item["delivery_state"],
                "deliveryError": (
                    json.loads(item["delivery_receipt_json"]).get("errorCode")
                    if item["delivery_receipt_json"]
                    else None
                ),
                "replyStatus": item["final_status"]
                or (json.loads(reports[-1]["result_json"])["status"] if reports else "unconfirmed"),
                "verified": False,
                "reports": [
                    {**json.loads(r["result_json"]), "createdMs": r["created_ms"]}
                    for r in reports[-5:]
                ],
            }

        return await self.db.call(read)
