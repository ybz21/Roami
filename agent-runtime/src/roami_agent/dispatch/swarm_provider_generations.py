"""Bind prepared native providers to stable members without rewriting old attempts."""

import json
from pathlib import Path

from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.executors.targets import TargetDirectory
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.swarm_repository import receipt


class PreparationRequired(Exception):
    pass


def prior_migration(db, owner, sid, spec):
    def pending():
        raise PreparationRequired

    return receipt(db, owner, spec["commandKey"], {"swarmId": sid, **spec}, pending, swarm_id=sid)


async def prepared_members(database, settings, value, spec):
    requested = [
        item
        for item in spec.get("members", [])
        if isinstance(item, dict) and item.get("preparedLaunchKey")
    ]
    if not requested:
        return {}
    if settings is None:
        raise DomainError("SWARM_PREPARATION_UNAVAILABLE", 409)
    target = json.loads(value["target_json"])
    if target.get("kind") != "project":
        raise DomainError("SWARM_PREPARATION_REQUIRES_PROJECT", 409)
    workspace = await TargetDirectory(settings).project_workspace(target["projectId"])
    observer = CodingExecutor(database, settings)
    proofs = {}
    sessions = set()
    for item in requested:
        proof = await observer.command("prepared", "--key", item["preparedLaunchKey"])
        validate_prepared_member(item, proof, workspace["directory"])
        if proof["sessionId"] in sessions:
            raise DomainError("SWARM_PROVIDER_ALREADY_BOUND", 409)
        sessions.add(proof["sessionId"])
        proofs[item["memberId"]] = proof
    return proofs


def validate_prepared_member(item, proof, directory):
    binding = proof.get("sessionBinding") or {}
    workspace = proof.get("workspace") or {}
    if (
        proof.get("ready") is not True
        or proof.get("launchKey") != item.get("preparedLaunchKey")
        or proof.get("executor") != item.get("executor")
        or proof.get("configuredModel") != item.get("model")
        or not isinstance(proof.get("sessionId"), str)
        or not proof["sessionId"]
        or binding.get("id") != proof["sessionId"]
        or binding.get("name") != proof["sessionId"]
        or not binding.get("providerConversationId")
        or not binding.get("tmuxId")
        or not binding.get("pane")
        or not binding.get("created")
        or not binding.get("hostProof")
        or not binding.get("directoryProof")
        or workspace.get("directory") != directory
        or binding.get("directory") != directory
        or not Path(directory).is_absolute()
    ):
        raise DomainError("SWARM_PREPARATION_UNCONFIRMED", 409)


def bind_prepared_member(db, value, member, generation, proof):
    if not proof:
        return
    if row(
        db,
        "SELECT conversation_id FROM project_okr_main_providers WHERE session_id=? OR provider_id=?",
        (proof["sessionId"], proof["sessionBinding"]["providerConversationId"]),
    ):
        raise DomainError("SWARM_PROVIDER_ALREADY_BOUND", 409)
    if row(
        db,
        "SELECT member_id FROM swarm_member_provider_generations WHERE session_id=? OR launch_key=? OR (provider_id=? AND member_id!=?)",
        (
            proof["sessionId"],
            proof["launchKey"],
            proof["sessionBinding"]["providerConversationId"],
            member["id"],
        ),
    ):
        raise DomainError("SWARM_PROVIDER_ALREADY_BOUND", 409)
    db.execute(
        "INSERT INTO swarm_member_provider_generations(member_id,generation,owner_id,swarm_id,launch_key,session_id,provider_id,executor,model,binding_json,workspace_json,created_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            member["id"],
            generation,
            value["owner_id"],
            value["id"],
            proof["launchKey"],
            proof["sessionId"],
            proof["sessionBinding"]["providerConversationId"],
            proof["executor"],
            proof["configuredModel"],
            encoded(proof["sessionBinding"]),
            encoded(proof["workspace"]),
            now_ms(),
        ),
    )


def provider_summary(db, member):
    provider = row(
        db,
        "SELECT generation,session_id AS sessionId,executor,model,launch_key AS launchKey FROM swarm_member_provider_generations WHERE member_id=? AND generation=?",
        (member["id"], member["execution_generation"]),
    )
    if provider and (
        provider["executor"] != member["executor"] or provider["model"] != member["model"]
    ):
        raise DomainError("SWARM_PROVIDER_BINDING_CONFLICT", 409)
    return provider


def provider_for_work(db, work_id):
    return row(
        db,
        "SELECT p.* FROM swarm_member_provider_generations p "
        "JOIN swarm_members m ON m.id=p.member_id AND m.execution_generation=p.generation "
        "JOIN swarm_member_work b ON b.member_id=m.id AND b.work_id=m.current_work_id "
        "JOIN swarm_work_items w ON w.id=b.work_id AND w.execution_generation=p.generation "
        "WHERE w.id=? AND p.executor=w.executor AND p.model=w.model",
        (work_id,),
    )
