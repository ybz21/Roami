import hashlib
import logging

from roami_agent.observability.execution_debug import CONTEXT_FIELDS
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded

log = logging.getLogger(__name__)


class PromptManifests:
    def __init__(self, database):
        self.db = database

    async def record(self, turn, attempt, model_key, wire_hash, plan, catalog, role):
        tid = turn["id"]
        step = attempt - 1
        await self.db.call(
            lambda db, step=step, wire_hash=wire_hash, plan=plan, catalog=catalog: db.execute(
                "INSERT INTO prompt_manifests(id,turn_id,attempt_no,provider_key,model_key,serializer_version,prefix_sha256,snapshot_id,memory_epoch,parts_json,created_ms) "
                "VALUES(?,?,?,?,?,'chat-v1',?,?,?,?,?)",
                (
                    identity(),
                    tid,
                    step + 1,
                    plan.get("providerKey", "unidentified"),
                    model_key,
                    wire_hash,
                    plan["snapshotId"],
                    plan.get("memoryEpoch", 1),
                    encoded(
                        {
                            "role": role,
                            "requestBasis": plan.get("requestBasis"),
                            "historyFingerprint": plan.get("historyFingerprint"),
                            "historyView": plan.get("historyView", "full"),
                            "suppressedHistoryCount": len(
                                plan.get("suppressedSourceMessageIds", [])
                            ),
                            "estimatedTokens": plan.get("estimatedTokens"),
                            "modelContext": {key: plan.get(key) for key in CONTEXT_FIELDS},
                            "requestLimits": plan.get("requestLimits"),
                            "executionTiming": plan.get("executionTiming"),
                            "sourceMessageIds": plan.get("sourceMessageIds", []),
                            "catalogHash": hashlib.sha256(encoded(catalog).encode()).hexdigest(),
                            "modelSettingsHash": plan.get("modelSettingsHash"),
                            "imageEvidence": plan.get("imageEvidence", []),
                            "attachmentEvidence": plan.get("attachmentEvidence", []),
                            "imageError": plan.get("imageError"),
                            "taskEvidence": plan.get("taskEvidence"),
                            "memoryEvidence": plan.get("memoryEvidence", []),
                            "timing": plan.get("timing"),
                        }
                    ),
                    now_ms(),
                ),
            ),
            write=True,
        )

    async def timing(self, turn, attempt, timing):
        try:
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE prompt_manifests SET parts_json=json_set(parts_json,'$.timing',json(?)) "
                    "WHERE turn_id=? AND attempt_no=?",
                    (encoded(timing), turn["id"], attempt),
                ),
                write=True,
            )
        except Exception:  # noqa: BLE001 - Diagnostics must not change the execution outcome.
            log.warning("Model timing could not be recorded")
