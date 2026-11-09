"""Append-only speech intent/result receipts; an uncertain request is never replayed."""

import hashlib
import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.publication_reviews import current_version
from roami_agent.storage.swarm_repository import receipt


def admit_media_speech(db, binding, payload):
    _, manifest = current_version(db, binding, payload["versionId"])
    selected = {manifest["content"].get(name) for name in ("video", "audio")}
    if payload["sourceArtifactId"] not in selected or not any(
        value["id"] == payload["sourceArtifactId"] and value["sha256"] == payload["sourceSha256"]
        for value in manifest["artifacts"]
    ):
        raise DomainError("PUBLICATION_MEDIA_NOT_SELECTED", 409)
    project = manifest["author"]["projectId"]
    key = "publication-media-speech:" + hashlib.sha256(encoded(payload).encode()).hexdigest()
    fresh = False

    def create():
        nonlocal fresh
        fresh = True
        return {
            "kind": "publication_media_speech_intent",
            "id": identity(),
            "key": key,
            "projectId": project,
            "swarmId": manifest["author"]["swarmId"],
            "createdTurnId": binding["turnId"],
            "toolCallId": binding.get("toolCallId"),
            **payload,
        }

    intent = receipt(
        db,
        binding["owner"],
        key,
        payload,
        create,
        swarm_id=manifest["author"]["swarmId"],
    )
    terminal = row(
        db,
        "SELECT receipt_json FROM swarm_commands WHERE owner_id=? "
        "AND scope_project_id=? AND command_key=?",
        (binding["owner"], project, "publication-media-speech-result:" + intent["id"]),
    )
    return {
        "fresh": fresh,
        "intent": intent,
        "result": json.loads(terminal["receipt_json"]) if terminal else None,
    }


def finish_media_speech(db, owner, intent, result):
    actual = row(
        db,
        "SELECT receipt_json FROM swarm_commands WHERE owner_id=? "
        "AND scope_project_id=? AND command_key=?",
        (owner, intent["projectId"], intent["key"]),
    )
    if not actual or json.loads(actual["receipt_json"]) != intent:
        raise DomainError("PUBLICATION_MEDIA_TRANSCRIPTION_UNVERIFIED", 409)
    payload = {"intentId": intent["id"], **result}
    return receipt(
        db,
        owner,
        "publication-media-speech-result:" + intent["id"],
        payload,
        lambda: {
            "kind": "publication_media_speech_result",
            **payload,
            "publicationAuthorized": False,
        },
        swarm_id=intent["swarmId"],
    )


def completed_media_speech(db, owner, project, payload, intent_id):
    key = "publication-media-speech:" + hashlib.sha256(encoded(payload).encode()).hexdigest()
    intent = row(
        db,
        "SELECT receipt_json FROM swarm_commands WHERE owner_id=? "
        "AND scope_project_id=? AND command_key=?",
        (owner, project, key),
    )
    result = row(
        db,
        "SELECT receipt_json FROM swarm_commands WHERE owner_id=? "
        "AND scope_project_id=? AND command_key=?",
        (owner, project, "publication-media-speech-result:" + str(intent_id)),
    )
    if not intent or not result:
        raise DomainError("PUBLICATION_MEDIA_TRANSCRIPTION_UNVERIFIED", 409)
    intent, result = json.loads(intent["receipt_json"]), json.loads(result["receipt_json"])
    if (
        intent.get("id") != intent_id
        or any(intent.get(k) != v for k, v in payload.items())
        or result.get("intentId") != intent_id
        or result.get("state") != "succeeded"
    ):
        raise DomainError("PUBLICATION_MEDIA_TRANSCRIPTION_UNVERIFIED", 409)
    return result
