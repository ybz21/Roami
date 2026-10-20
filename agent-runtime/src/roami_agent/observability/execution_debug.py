"""Owner/branch-scoped request history and queue snapshots for the debug page."""

from roami_agent.observability.execution_traces import origin_turn
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import row, rows
from roami_agent.storage.transcript_repository import owned

CONTEXT_FIELDS = (
    "estimatedTokens",
    "estimator",
    "usageTokens",
    "trailingTokens",
    "historyTokens",
    "instructionTokens",
    "toolTokens",
    "inputBudget",
    "contextWindow",
    "reserveTokens",
    "compactionThreshold",
    "compactionRatio",
    "capacityBasis",
    "snapshotId",
    "branchId",
    "branchEpoch",
    "memoryEpoch",
)
TASK_ACTIVE = "('queued','preparing','running','verifying','cancelling','waiting_user')"


def debug_page(db, sql, arguments, offset, limit):
    total = db.execute("SELECT COUNT(*) FROM (" + sql + ")", arguments).fetchone()[0]
    items = rows(
        db,
        "SELECT * FROM (" + sql + ") ORDER BY createdMs DESC,id DESC LIMIT ? OFFSET ?",
        (*arguments, limit, offset),
    )
    return {
        "items": items,
        "total": total,
        "nextOffset": offset + limit if total > offset + limit else None,
    }


class ExecutionDebug:
    def __init__(self, database, context, settings, traces):
        self.db, self.context, self.settings, self.traces = database, context, settings, traces

    @staticmethod
    def branch(db, owner, cid, branch_id):
        conversation = owned(db, owner, cid)
        branch_id = branch_id or conversation["active_branch_id"]
        if not row(
            db, "SELECT id FROM branches WHERE id=? AND conversation_id=?", (branch_id, cid)
        ):
            raise DomainError("BRANCH_NOT_FOUND", 404)
        return branch_id

    async def snapshot(
        self,
        owner,
        cid,
        *,
        branch_id=None,
        minutes=60,
        offset=0,
        queue_offset=0,
        task_offset=0,
        limit=50,
        include_context=False,
    ):
        if (
            minutes not in {15, 60, 1440}
            or not 1 <= limit <= 200
            or min(offset, queue_offset, task_offset) < 0
        ):
            raise DomainError("INVALID_DEBUG_QUERY")

        def read(db):
            bid = self.branch(db, owner, cid, branch_id)
            timestamp = now_ms()
            requests = debug_page(
                db,
                "SELECT u.id,'turn' AS kind,u.state,u.created_ms AS createdMs,u.finished_ms AS finishedMs,"
                "(SELECT CASE WHEN EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id) "
                "THEN NULL ELSE substr(json_extract(m.content_json,'$.text'),1,160) END FROM messages m "
                "WHERE m.turn_id=u.id AND m.role='user' AND m.deleted_ms IS NULL ORDER BY m.seq LIMIT 1) AS preview "
                "FROM turns u WHERE u.conversation_id=? AND u.branch_id=? AND u.trigger_kind='user' AND u.created_ms>=?",
                (owner, cid, bid, timestamp - minutes * 60_000),
                offset,
                limit,
            )
            turns = debug_page(
                db,
                "SELECT u.id,u.trigger_kind AS triggerKind,u.state,u.created_ms AS createdMs,"
                "j.state AS jobState,j.available_ms AS availableMs,"
                "COALESCE(json_extract(j.payload_json,'$.deferred'),0) AS deferred "
                "FROM turns u LEFT JOIN jobs j ON j.kind='turn.run' AND j.aggregate_id=u.id "
                "WHERE u.conversation_id=? AND u.branch_id=? AND u.state IN ('queued','running')",
                (cid, bid),
                queue_offset,
                limit,
            )
            tasks = debug_page(
                db,
                "SELECT t.id,t.state,t.revision,t.created_ms AS createdMs,"
                "json_extract(t.intent_json,'$.executor') AS executor,m.turn_id AS originTurnId,"
                "a.state AS attemptState,a.started_ms AS startedMs,"
                "a.session_id AS sessionId FROM tasks t JOIN messages m ON m.id=t.origin_message_id "
                "LEFT JOIN task_attempts a ON a.id=(SELECT id FROM task_attempts WHERE task_id=t.id "
                "AND task_revision=t.revision ORDER BY attempt_no DESC LIMIT 1) "
                "WHERE t.owner_id=? AND t.origin_conversation_id=? AND t.origin_branch_id=? "
                "AND t.state IN " + TASK_ACTIVE,
                (owner, cid, bid),
                task_offset,
                limit,
            )
            tasks["activeTotal"] = db.execute(
                "SELECT COUNT(*) FROM tasks WHERE owner_id=? AND origin_conversation_id=? "
                "AND origin_branch_id=? AND state IN ('queued','preparing','running','verifying','cancelling')",
                (owner, cid, bid),
            ).fetchone()[0]
            compactions = rows(
                db,
                "SELECT id,state,available_ms AS availableMs FROM jobs WHERE kind='context.compact' "
                "AND state IN ('queued','running') AND json_extract(payload_json,'$.ownerId')=? "
                "AND json_extract(payload_json,'$.conversationId')=? AND json_extract(payload_json,'$.branchId')=? ORDER BY rowid",
                (owner, cid, bid),
            )
            return {
                "conversationId": cid,
                "branchId": bid,
                "observedMs": timestamp,
                "windowMinutes": minutes,
                "requests": requests,
                "queue": {"turns": turns, "tasks": tasks, "compactions": compactions},
                "active": bool(turns["total"] or compactions or tasks["activeTotal"]),
                "scheduler": {
                    "mainSlots": self.settings.main_concurrency,
                    "workerSlots": self.settings.workers,
                },
                "limits": {
                    "modelTimeoutSeconds": self.settings.timeout_for("main"),
                    "maxDepth": self.settings.max_depth,
                },
            }

        result = await self.db.call(read)
        if include_context:
            configuration = self.context.request_context()
            projected = await self.context.project(
                owner, cid, branch_id=result["branchId"], request_context=configuration
            )
            result["context"] = {key: projected.get(key) for key in CONTEXT_FIELDS}
            result["context"]["model"] = configuration["route"].get("name")
        return result

    async def trace(self, owner, cid, *, branch_id=None, turn_id=None, task_id=None, chrome=False):
        def validate(db):
            bid = self.branch(db, owner, cid, branch_id)
            if bool(turn_id) == bool(task_id):
                raise DomainError("TRACE_ONE_TARGET_REQUIRED")
            target = origin_turn(db, owner, turn_id=turn_id, task_id=task_id)
            if target.get("conversation_id") != cid or target.get("branch_id") != bid:
                raise DomainError("TRACE_NOT_FOUND", 404)

        await self.db.call(validate)
        return await self.traces.get(owner, turn_id=turn_id, task_id=task_id, chrome=chrome)
