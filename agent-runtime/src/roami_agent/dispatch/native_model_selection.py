"""Reconcile a native model control against its existing launch and provider."""

import json
import re

from roami_agent.dispatch.swarm_provider_generations import validate_prepared_member
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.providers.native_conversation import NativeConversation
from roami_agent.storage.database import row

BEFORE_INPUT = {"SESSION_MODEL_SELECTION_TARGET_UNCONFIRMED", "SESSION_MODEL_PICKER_NOT_OPENED"}


def claim_model_selection(db, job_id, kind):
    current = row(
        db,
        "SELECT * FROM jobs WHERE id=? AND kind=? AND state='queued' AND available_ms<=?",
        (job_id, kind, now_ms()),
    )
    if current:
        db.execute(
            "UPDATE jobs SET attempts=attempts+1,available_ms=? WHERE id=?",
            (now_ms() + 60_000, current["id"]),
        )
    return current


def model_selection_still_claimed(db, operation):
    return row(
        db,
        "SELECT id FROM jobs WHERE id=? AND state='queued' AND attempts=?",
        (operation["id"], operation["attempts"] + 1),
    )


async def select_bound_model(command, prior, request, unconfirmed):
    selected = await command("select-model", "--file", "-", spec=request)
    prepared = await command("prepared", "--key", request["preparedFrom"])
    proof = selected.get("proof")
    digest = proof.get("sourceSha256") if isinstance(proof, dict) else None
    if (
        any(selected.get(key) != value for key, value in request.items())
        or selected.get("allowMetered", False) is not request.get("allowMetered", False)
        or selected.get("sessionId") != prior["session_id"]
        or selected.get("providerConversationId") != prior["provider_id"]
        or not isinstance(digest, str)
        or not re.fullmatch(r"[a-f0-9]{64}", digest)
    ):
        raise DomainError(unconfirmed, 409)
    binding = json.loads(prior["binding_json"])
    validate_prepared_member(
        {"preparedLaunchKey": prior["launch_key"], "executor": "claude", "model": request["model"]},
        prepared,
        binding["directory"],
    )
    NativeConversation({**prior, "binding": binding}, {}, command).verify(
        {"session": prepared["sessionId"], "sessionBinding": prepared["sessionBinding"]}
    )
    return selected
