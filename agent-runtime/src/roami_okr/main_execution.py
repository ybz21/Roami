"""Project Main provider bindings keep the existing conversation and team identity."""

import json
import logging
import re
import sqlite3
from copy import copy

from roami_agent.conversation.idle import assert_main_idle
from roami_agent.dispatch.swarm_provider_generations import (
    require_member_provider_available,
    validate_prepared_member,
)
from roami_agent.executors.targets import TargetDirectory
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, row, rows
from roami_agent.storage.swarm_repository import receipt
from roami_agent.storage.transcript_repository import owned
from roami_okr.intake import assert_project_main
from roami_okr.main_model_selection import main_model_selection_status, pending_model_selection
from roami_okr.main_review_model import main_review_route
from roami_okr.native_main import NativeMain
from roami_okr.settled_route_recovery import recover_route_wait, recovery_candidates

log = logging.getLogger(__name__)
MAIN_LAUNCH_KEY = re.compile(
    r"project-main:([a-f0-9]{32}):[a-f0-9]{24}(?::retry-[1-9][0-9]{0,18})?"
)


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


def project_main_session_ids(db, owner, swarm):
    return [
        item["session_id"]
        for item in rows(
            db,
            "SELECT p.session_id FROM project_okr_main_providers p JOIN project_okr_mains m "
            "ON m.owner_id=p.owner_id AND m.project_id=p.project_id "
            "AND m.conversation_id=p.conversation_id "
            "WHERE m.owner_id=? AND m.project_id=? AND m.conversation_id=?",
            (owner, swarm["target"].get("projectId"), swarm["mainConversationId"]),
        )
    ]


def require_project_provider_available(db, session_id, provider_id):
    if row(
        db,
        "SELECT 1 FROM project_okr_main_providers WHERE session_id=? OR provider_id=?",
        (session_id, provider_id),
    ):
        raise DomainError("SWARM_PROVIDER_ALREADY_BOUND", 409)


class NativeMainModelCommands:
    def __init__(self, binding):
        self.model = binding["model"]
        self.executor = binding["executor"]
        self.session_id = binding["session_id"]

    def check_model(self, model):
        if model and model not in {self.model, "roami-claude/" + self.model}:
            raise DomainError("PROJECT_MAIN_MODEL_CONFLICT", 409)

    def check_compact(self):
        raise DomainError("PROJECT_MAIN_NATIVE_COMMAND_REQUIRED", 409)


def conversation_model_binding(db, owner, cid):
    binding = main_binding(db, owner, cid)
    return NativeMainModelCommands(binding) if binding is not None else None


def main_configuration(db, owner, cid):
    owned(db, owner, cid)
    if not row(
        db,
        "SELECT project_id FROM project_okr_mains WHERE owner_id=? AND conversation_id=?",
        (owner, cid),
    ):
        raise DomainError("PROJECT_MAIN_IDENTITY_MISMATCH", 409)
    value = main_binding(db, owner, cid)
    config = (
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
    if selection := pending_model_selection(db, cid):
        config["modelSelection"] = main_model_selection_status(selection)
    if review := main_review_route(db, owner, cid):
        config["reviewRoute"] = review
    return config


class MainExecutions:
    def __init__(self, database, settings, executor, *, capabilities=None):
        self.db, self.settings, self.executor = database, settings, executor
        self.capabilities = capabilities

    async def configure(self, owner, cid, spec):
        project = spec["projectId"]
        provider_source = spec.get("recoverProviderFromLaunchKey")
        if provider_source and spec.get("recoverFromLaunchKey"):
            raise DomainError("PROJECT_MAIN_PROVIDER_RECOVERY_UNCONFIRMED", 409)

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
        original = recovery = source_turn = None
        if provider_source or spec.get("recoverFromLaunchKey"):
            original = await self.db.call(lambda db: main_binding(db, owner, cid))
        if provider_source:
            source_turn = await self.provider_recovery(original, spec, proof)
        elif proof.get("recoveredFrom"):
            raise DomainError("PROJECT_MAIN_PROVIDER_RECOVERY_UNCONFIRMED", 409)
        elif spec.get("recoverFromLaunchKey"):
            recovery = await self.context_rejection(original, spec, workspace["directory"])

        def write(db):
            assert_project_main(db, owner, cid, project)

            def apply():
                conversation = owned(db, owner, cid)
                if pending_model_selection(db, cid):
                    raise DomainError("PROJECT_MAIN_MODEL_SELECTION_PENDING", 409)
                # Queued turns resolve the provider after admission; running turns already own it.
                assert_main_idle(db, conversation, allow_queued=bool(recovery or provider_source))
                if not provider_source and row(
                    db,
                    "SELECT id FROM swarm_groups WHERE owner_id=? AND conversation_id=? AND archived=0 AND paused=0",
                    (owner, cid),
                ):
                    raise DomainError("SWARM_MIGRATION_REQUIRES_PAUSE", 409)
                current = main_binding(db, owner, cid)
                generation = current["generation"] if current else 0
                if generation != spec["expectedGeneration"]:
                    raise DomainError("PROJECT_MAIN_GENERATION_CHANGED", 409)
                if current and (not (recovery or provider_source) or original != current):
                    raise DomainError("PROJECT_MAIN_REPLACEMENT_REQUIRES_STOP", 409)
                if source_turn and not row(
                    db,
                    "SELECT id FROM turns WHERE id=? AND conversation_id=? AND branch_id=? "
                    "AND state IN ('completed','failed','interrupted','cancelled')",
                    (source_turn, cid, conversation["active_branch_id"]),
                ):
                    raise DomainError("PROJECT_MAIN_PROVIDER_RECOVERY_UNCONFIRMED", 409)
                if recovery is not None:
                    turn_id, refusal = recovery
                    if not row(
                        db,
                        "SELECT id FROM turns WHERE id=? AND conversation_id=? AND branch_id=? "
                        "AND state='failed' AND finished_ms>=?",
                        (turn_id, cid, conversation["active_branch_id"], refusal["finishedMs"]),
                    ):
                        raise DomainError("PROJECT_MAIN_CONTEXT_REJECTION_UNCONFIRMED", 409)
                binding = proof["sessionBinding"]
                require_member_provider_available(
                    db,
                    proof["sessionId"],
                    binding["providerConversationId"],
                    launch_key=proof["launchKey"],
                )
                if provider_source:
                    if row(
                        db,
                        "SELECT 1 FROM project_okr_main_providers WHERE session_id=? OR launch_key=?",
                        (proof["sessionId"], proof["launchKey"]),
                    ):
                        raise DomainError("SWARM_PROVIDER_ALREADY_BOUND", 409)
                else:
                    require_project_provider_available(
                        db, proof["sessionId"], binding["providerConversationId"]
                    )
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
                details = {**result}
                if recovery:
                    details["previousContextRejection"] = recovery[1]
                if provider_source:
                    details["recoveredFrom"] = provider_source
                event(
                    db,
                    cid,
                    "project.main.execution.changed",
                    details,
                )
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

    async def provider_recovery(self, original, spec, proof):
        source_key = spec["recoverProviderFromLaunchKey"]
        if (
            not original
            or original["generation"] != spec["expectedGeneration"]
            or original["executor"] != "claude"
            or spec["executor"] != "claude"
            or proof.get("recoveredFrom") != source_key
            or proof["sessionId"] == original["session_id"]
        ):
            raise DomainError("PROJECT_MAIN_PROVIDER_RECOVERY_UNCONFIRMED", 409)
        launch = MAIN_LAUNCH_KEY.fullmatch(source_key)
        if not launch and source_key != original["launch_key"]:
            raise DomainError("PROJECT_MAIN_PROVIDER_RECOVERY_UNCONFIRMED", 409)
        existing = json.loads(original["binding_json"])
        rebinding = proof["sessionBinding"]
        if any(
            not existing.get(field) or rebinding.get(field) != existing[field]
            for field in (
                "providerConversationId",
                "hostProof",
                "directory",
                "directoryProof",
                "providerHome",
                "providerHomeProof",
            )
        ) or rebinding.get("providerHomeExplicit") != existing.get("providerHomeExplicit"):
            raise DomainError("PROJECT_MAIN_PROVIDER_RECOVERY_UNCONFIRMED", 409)
        terminal = await self.executor.command("status", "--key", source_key)
        NativeMain({**original, "binding": existing}, {}, self.executor.command).verify(terminal)
        result = terminal.get("result")
        if (
            not isinstance(result, dict)
            or result.get("state") not in {"succeeded", "failed", "cancelled"}
            or result.get("state") != terminal.get("state")
            or result.get("inputStopped") is not True
            or result.get("outcomeKnown") is not True
        ):
            raise DomainError("PROJECT_MAIN_PROVIDER_RECOVERY_UNCONFIRMED", 409)
        return launch[1] if launch else None

    async def context_rejection(self, original, spec, directory):
        key = spec["recoverFromLaunchKey"]
        launch = MAIN_LAUNCH_KEY.fullmatch(key)
        if (
            not launch
            or not original
            or original["generation"] != spec["expectedGeneration"]
            or original["executor"] != "claude"
            or original["executor"] != spec["executor"]
            or original["model"] != spec["model"]
        ):
            raise DomainError("PROJECT_MAIN_CONTEXT_REJECTION_UNCONFIRMED", 409)
        proof = await self.executor.command("prepared", "--key", original["launch_key"])
        validate_prepared_member(
            {**spec, "preparedLaunchKey": original["launch_key"]}, proof, directory
        )
        native = {**original, "binding": json.loads(original["binding_json"])}
        NativeMain(native, {}, self.executor.command).verify(
            {"session": proof["sessionId"], "sessionBinding": proof["sessionBinding"]}
        )
        refusal = proof.get("contextRejection")
        digest = refusal.get("stopEvidenceSha256") if isinstance(refusal, dict) else None
        if (
            not isinstance(refusal, dict)
            or refusal.get("launchKey") != key
            or refusal.get("code") != "CLAUDE_COMPACTION_INPUT_REJECTED"
            or not isinstance(digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or type(refusal.get("finishedMs")) is not int
            or refusal["finishedMs"] <= 0
        ):
            raise DomainError("PROJECT_MAIN_CONTEXT_REJECTION_UNCONFIRMED", 409)
        return launch[1], refusal

    async def loop_for(self, loop, turn):
        owner, cid = turn["owner_id"], turn["conversation_id"]
        binding, review = await self.db.call(
            lambda db: (main_binding(db, owner, cid), main_review_route(db, owner, cid))
        )
        if binding is None:
            return loop
        binding["binding"] = json.loads(binding.pop("binding_json"))
        selected = copy(loop)
        if review and review["model"] is not None and selected.reply_reviewer is not None:
            selected.review_route = (review["model"], review["freeOnly"])

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
