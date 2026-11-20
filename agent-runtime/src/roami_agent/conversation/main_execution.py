"""Project Main provider bindings keep the existing conversation and team identity."""

import json
import logging
import sqlite3
from copy import copy

from roami_agent.conversation.project_wakeup import assert_main_idle, assert_project_main
from roami_agent.dispatch.swarm_provider_generations import validate_prepared_member
from roami_agent.executors.targets import TargetDirectory
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.providers.native_main import NativeMain
from roami_agent.storage.database import event, row
from roami_agent.storage.swarm_repository import receipt
from roami_agent.storage.swarm_settled_route_recovery import recover_route_wait, recovery_candidates
from roami_agent.storage.transcript_repository import owned

log = logging.getLogger(__name__)


class NeedMainPreparation(Exception):
    pass


def main_binding(db, owner, cid):
    return row(
        db,
        "SELECT p.* FROM project_okr_main_providers p JOIN project_okr_mains m "
        "ON m.owner_id=p.owner_id AND m.project_id=p.project_id AND m.conversation_id=p.conversation_id "
        "WHERE p.owner_id=? AND p.conversation_id=? ORDER BY p.generation DESC LIMIT 1",
        (owner, cid),
    )


def main_configuration(db, owner, cid):
    owned(db, owner, cid)
    if not row(
        db,
        "SELECT project_id FROM project_okr_mains WHERE owner_id=? AND conversation_id=?",
        (owner, cid),
    ):
        raise DomainError("PROJECT_MAIN_IDENTITY_MISMATCH", 409)
    value = main_binding(db, owner, cid)
    return (
        {"generation": 0, "executor": "roami", "conversationId": cid}
        if value is None
        else {
            "generation": value["generation"],
            "executor": value["executor"],
            "model": value["model"],
            "conversationId": cid,
            "sessionId": value["session_id"],
            "projectId": value["project_id"],
        }
    )


class MainExecutions:
    def __init__(self, database, settings, executor, *, capabilities=None):
        self.db, self.settings, self.executor = database, settings, executor
        self.capabilities = capabilities

    async def configure(self, owner, cid, spec):
        project = spec["projectId"]

        def prior(db):
            assert_project_main(db, owner, cid, project)

            def pending():
                raise NeedMainPreparation

            return receipt(
                db,
                owner,
                spec["commandKey"],
                {"mainConversationId": cid, **spec},
                pending,
                scope_project_id=project,
            )

        try:
            return await self.db.call(prior)
        except NeedMainPreparation:
            pass
        workspace = await TargetDirectory(self.settings).project_workspace(project)
        proof = await self.executor.command("prepared", "--key", spec["preparedLaunchKey"])
        validate_prepared_member(spec, proof, workspace["directory"])

        def write(db):
            assert_project_main(db, owner, cid, project)

            def apply():
                conversation = owned(db, owner, cid)
                assert_main_idle(db, conversation)
                if row(
                    db,
                    "SELECT id FROM swarm_groups WHERE owner_id=? AND conversation_id=? AND archived=0 AND paused=0",
                    (owner, cid),
                ):
                    raise DomainError("SWARM_MIGRATION_REQUIRES_PAUSE", 409)
                current = main_binding(db, owner, cid)
                generation = current["generation"] if current else 0
                if generation != spec["expectedGeneration"]:
                    raise DomainError("PROJECT_MAIN_GENERATION_CHANGED", 409)
                if current:
                    # Retiring a live native provider needs its own stopped proof.
                    raise DomainError("PROJECT_MAIN_REPLACEMENT_REQUIRES_STOP", 409)
                binding = proof["sessionBinding"]
                if row(
                    db,
                    "SELECT member_id FROM swarm_member_provider_generations WHERE session_id=? OR provider_id=?",
                    (proof["sessionId"], binding["providerConversationId"]),
                ) or row(
                    db,
                    "SELECT conversation_id FROM project_okr_main_providers WHERE session_id=? OR provider_id=?",
                    (proof["sessionId"], binding["providerConversationId"]),
                ):
                    raise DomainError("SWARM_PROVIDER_ALREADY_BOUND", 409)
                db.execute(
                    "INSERT INTO project_okr_main_providers VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        owner,
                        project,
                        cid,
                        generation + 1,
                        spec["executor"],
                        spec["model"],
                        proof["launchKey"],
                        proof["sessionId"],
                        binding["providerConversationId"],
                        encoded(binding),
                        now_ms(),
                    ),
                )
                result = main_configuration(db, owner, cid)
                event(db, cid, "project.main.execution.changed", result)
                return result

            return receipt(
                db,
                owner,
                spec["commandKey"],
                {"mainConversationId": cid, **spec},
                apply,
                scope_project_id=project,
            )

        return await self.db.call(write, write=True)

    async def loop_for(self, loop, turn):
        binding = await self.db.call(
            lambda db: main_binding(db, turn["owner_id"], turn["conversation_id"])
        )
        if binding is None:
            return loop
        binding["binding"] = json.loads(binding.pop("binding_json"))
        selected = copy(loop)

        async def observe_delivery(launch_key, state):
            def write(db):
                current = main_binding(db, turn["owner_id"], turn["conversation_id"])
                if not current or current["generation"] != binding["generation"]:
                    return
                active = row(
                    db,
                    "SELECT 1 FROM turns t JOIN conversations c ON c.id=t.conversation_id "
                    "AND c.active_branch_id=t.branch_id WHERE t.id=? AND c.id=? AND t.state='running' "
                    "AND t.lease_epoch=? AND c.deleted_ms IS NULL",
                    (turn["id"], turn["conversation_id"], turn["lease_epoch"]),
                )
                key = f"native-delivery:{launch_key}:{turn['lease_epoch']}:{state}"
                if active and not row(db, "SELECT 1 FROM events WHERE event_key=?", (key,)):
                    event(
                        db,
                        turn["conversation_id"],
                        "turn.native_delivery",
                        {"state": state, "leaseEpoch": turn["lease_epoch"]},
                        turn_id=turn["id"],
                        key=key,
                    )

            try:
                await self.db.call(write, write=True)
            except (DomainError, OSError, sqlite3.Error):
                log.debug("Native delivery observation could not be recorded", exc_info=True)

        selected.model = NativeMain(
            binding,
            turn,
            self.executor.command,
            capabilities=self.capabilities,
            delivery=observe_delivery,
        )
        return selected

    async def recover_settled_route_waits(self):
        for turn in await self.db.call(recovery_candidates):
            try:
                await self._recover_settled_route_wait(turn)
            except (DomainError, OSError, TimeoutError):
                log.debug("Original Main route wait could not be recovered", exc_info=True)

    async def _recover_settled_route_wait(self, turn):
        owner, cid = turn["owner_id"], turn["conversation_id"]
        binding = await self.db.call(lambda db: main_binding(db, owner, cid))
        if not binding or binding["executor"] != "claude":
            return
        proof = await self.executor.command("prepared", "--key", binding["launch_key"])
        if (
            proof.get("ready") is not True
            or proof.get("executor") != binding["executor"]
            or proof.get("configuredModel") != binding["model"]
            or proof.get("launchKey") != binding["launch_key"]
            or not isinstance(proof.get("sessionBinding"), dict)
            or not proof.get("routeRefusal")
        ):
            return
        native = dict(binding)
        native["binding"] = json.loads(native.pop("binding_json"))
        model = NativeMain(native, turn, self.executor.command)
        model.verify({"session": proof.get("sessionId"), "sessionBinding": proof["sessionBinding"]})
        await self.db.call(
            lambda db: (
                main_binding(db, owner, cid) == binding
                and recover_route_wait(db, turn["id"], model, proof)
            ),
            write=True,
        )
