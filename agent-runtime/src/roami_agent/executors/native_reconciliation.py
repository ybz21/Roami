"""Release abandoned workspace fences only from durable, run-scoped stop evidence."""

import hashlib
import json
import os

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, row, rows
from roami_agent.tools.process import execute


class NativeWorkspaceReconciliation:
    def __init__(self, database, settings, *, command=None, resources=None):
        self.db, self.settings = database, settings
        self.command = command or self._command
        self.resources = resources
        self.cursor = ""

    async def _command(self, key, proof):
        paths = self.db.instance_paths
        if not paths:
            raise DomainError("NATIVE_RECONCILIATION_UNAVAILABLE", 503)
        environment = {
            name: value
            for name, value in os.environ.items()
            if name not in self.settings.provider_key_environments()
        }
        for name, field in [
            ("ROAMI_HOME", "homeRoot"),
            ("ROAMI_DATA", "dataRoot"),
            ("ROAMI_DATABASE_DIR", "databaseRoot"),
            ("ROAMI_BACKUP_DIR", "backupRoot"),
        ]:
            value = paths.get(field)
            if not isinstance(value, str) or not os.path.isabs(value):
                raise DomainError("NATIVE_RECONCILIATION_UNAVAILABLE", 503)
            environment[name] = value
        response = await execute(
            [
                self.settings.cli_bin,
                "agent",
                "execution",
                "reconcile-native",
                "--key",
                key,
                "--file",
                "-",
            ],
            input_data=encoded(proof).encode(),
            timeout=8,
            env=environment,
        )
        if response["exitCode"]:
            raise DomainError("NATIVE_RECONCILIATION_UNAVAILABLE", 503)
        try:
            return json.loads(response["stdout"])
        except (ValueError, TypeError) as exc:
            raise DomainError("INVALID_NATIVE_RECONCILIATION_RECEIPT") from exc

    @staticmethod
    def _proof(db, run):
        current = row(db, "SELECT * FROM task_attempts WHERE id=?", (run["id"],))
        if (
            not current
            or current["executor_kind"] != "native"
            or current["state"] in {"accepted", "starting", "running"}
        ):
            return None
        if row(
            db,
            "SELECT id FROM jobs WHERE kind='task.run' AND state='running' "
            "AND aggregate_id=? AND json_extract(payload_json,'$.runId')=?",
            (run["task_id"], run["id"]),
        ):
            return None
        sources = rows(
            db,
            "SELECT e.turn_id FROM events e JOIN turns t ON t.id=e.turn_id "
            "WHERE e.task_id=? AND e.kind='task.preparing' "
            "AND json_extract(e.payload_json,'$.runId')=? "
            "AND json_extract(e.payload_json,'$.nativeTurnId')=e.turn_id "
            "AND t.branch_id=? AND t.state IN ('completed','failed','interrupted','cancelled') "
            "ORDER BY e.id LIMIT 2",
            (run["task_id"], run["id"], current["native_branch_id"]),
        )
        if len(sources) != 1:
            return None
        calls = rows(
            db,
            "SELECT id,tool_name,state,idempotency_key FROM tool_calls "
            "WHERE turn_id=? AND effect='write' ORDER BY id LIMIT 257",
            (sources[0]["turn_id"],),
        )
        actions = rows(
            db,
            "SELECT a.id,a.state,a.idempotency_key,a.result_json,r.kind FROM resource_actions a "
            "JOIN resources r ON r.id=a.resource_id WHERE a.task_id=? AND a.run_id=? "
            "AND r.owner_id=? ORDER BY a.id LIMIT 257",
            (run["task_id"], run["id"], run["owner_id"]),
        )
        if len(calls) > 256 or len(actions) > 256:
            return None
        for action in actions:
            if action["state"] == "running":
                return None
            try:
                result = json.loads(action["result_json"] or "{}")
            except (ValueError, TypeError):
                return None
            if not isinstance(result, dict) or result.get("inputStopped") is not True:
                return None
        for call in calls:
            if call["state"] in {"planned", "running"}:
                return None
            if call["state"] == "unknown":
                if call["tool_name"] not in {"browser_open", "browser_act", "computer_act"}:
                    return None
                kind, suffixes = {
                    "browser_open": ("browser", [":create", ":navigate"]),
                    "browser_act": ("browser", [":act"]),
                    "computer_act": ("desktop", [":desktop"]),
                }[call["tool_name"]]
                if not any(
                    action["kind"] == kind
                    and action["idempotency_key"]
                    in {call["idempotency_key"] + suffix for suffix in suffixes}
                    for action in actions
                ):
                    return None
            elif call["state"] not in {"succeeded", "failed", "cancelled"}:
                return None
        return {
            "taskId": run["task_id"],
            "runId": run["id"],
            "revision": current["task_revision"],
            "nativeTurnId": sources[0]["turn_id"],
            "toolCallIds": [call["id"] for call in calls],
            "actionIds": [action["id"] for action in actions],
        }

    async def tick(self):
        pending = await self.db.call(
            lambda db: rows(
                db,
                "SELECT a.*,t.owner_id,t.origin_conversation_id FROM task_attempts a "
                "JOIN tasks t ON t.id=a.task_id JOIN conversations c ON c.id=t.origin_conversation_id "
                "AND c.owner_id=t.owner_id WHERE a.executor_kind='native' "
                "AND a.state IN ('unknown','failed','interrupted','cancelled') AND a.id>? "
                "AND COALESCE(json_extract(t.target_json,'$.workspace.taskDirectory'),0)=0 "
                "AND NOT EXISTS(SELECT 1 FROM events e WHERE e.event_key='native-workspace-reconciled:'||a.id) "
                "ORDER BY a.id LIMIT 8",
                (self.cursor,),
            )
        )
        self.cursor = pending[-1]["id"] if pending else ""
        for run in pending:
            proof = await self.db.call(lambda db, run=run: self._proof(db, run))
            if proof is None:
                continue
            digest = hashlib.sha256(encoded(proof).encode()).hexdigest()
            try:
                receipt = await self.command(
                    run["launch_id"], {"stopped": True, "evidenceSha256": digest}
                )
                if (
                    not isinstance(receipt, dict)
                    or receipt.get("released") is not True
                    or receipt.get("inputStopped") is not True
                    or receipt.get("launchKey") != run["launch_id"]
                    or receipt.get("evidenceSha256") != digest
                    or not isinstance(receipt.get("workspaceId"), str)
                    or not 1 <= len(receipt["workspaceId"]) <= 200
                ):
                    raise DomainError("INVALID_NATIVE_RECONCILIATION_RECEIPT")
            except (DomainError, OSError, TimeoutError):
                continue

            if self.resources:
                await self.resources.release_task(run["owner_id"], run["task_id"], run["id"])

            def record(db, run=run, proof=proof, receipt=receipt, digest=digest):
                if self._proof(db, run) != proof:
                    return
                event(
                    db,
                    run["origin_conversation_id"],
                    "task.native_workspace_reconciled",
                    {
                        "taskId": run["task_id"],
                        "runId": run["id"],
                        "taskRevision": run["task_revision"],
                        "workspaceId": receipt["workspaceId"],
                        "inputStopped": True,
                        "goalStatePreserved": True,
                        "evidenceSha256": digest,
                    },
                    task_id=run["task_id"],
                    key="native-workspace-reconciled:" + run["id"],
                )

            await self.db.call(record, write=True)
