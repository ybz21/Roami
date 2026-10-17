import hashlib

from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded


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
                    "chat-completions",
                    model_key,
                    wire_hash,
                    plan["snapshotId"],
                    plan.get("memoryEpoch", 1),
                    encoded(
                        {
                            "role": role,
                            "sourceMessageIds": plan.get("sourceMessageIds", []),
                            "catalogHash": hashlib.sha256(encoded(catalog).encode()).hexdigest(),
                        }
                    ),
                    now_ms(),
                ),
            ),
            write=True,
        )
