"""Select contact sheets from successful current-Main media-image receipts."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.image_limits import MAX_CONTEXT_IMAGES
from roami_agent.storage.database import row
from roami_agent.storage.publication_media_reads import media_tool_artifact
from roami_agent.storage.publication_reviews import current_version


async def main_media_images(database, turn, plan, prompt):
    if not turn.get("id") or turn.get("executionRunId"):
        return [], []
    sources, unavailable, seen = [], [], set()
    for message in reversed(prompt[plan.get("currentTurnStart", 0) + 1 :]):
        if message.get("role") != "tool" or not isinstance(message.get("content"), str):
            continue
        try:
            value = json.loads(message["content"])
        except (TypeError, ValueError):
            continue
        image = value.get("mediaImage") if isinstance(value, dict) else None
        if not isinstance(image, dict) or not all(
            isinstance(image.get(key), str)
            for key in ("artifactId", "sha256", "versionId", "sourceArtifactId", "sourceSha256")
        ):
            continue
        if image["artifactId"] in seen:
            continue
        seen.add(image["artifactId"])

        def read(db, image=image, message=message):
            call = row(
                db,
                "SELECT x.assistant_message_id FROM tool_calls x JOIN messages m ON m.id=x.result_message_id "
                "WHERE x.turn_id=? AND x.idempotency_key=? AND x.tool_name='swarm_publication_media' "
                "AND x.state='succeeded' AND json_extract(x.arguments_json,'$.operation')='image' "
                "AND json_extract(x.arguments_json,'$.versionId')=? "
                "AND json_extract(json_extract(m.content_json,'$.text'),'$.mediaImage.artifactId')=? "
                "AND m.turn_id=x.turn_id AND m.conversation_id=? AND m.branch_id=? "
                "AND m.role='tool' AND m.status='completed' AND m.deleted_ms IS NULL",
                (
                    turn["id"],
                    turn["id"] + ":" + message.get("tool_call_id", ""),
                    image["versionId"],
                    image["artifactId"],
                    turn["conversation_id"],
                    turn["branch_id"],
                ),
            )
            if not call:
                return None
            current_version(
                db,
                {
                    "owner": turn["owner_id"],
                    "role": "main",
                    "conversation": turn["conversation_id"],
                    "turnId": turn["id"],
                    "leaseEpoch": turn["lease_epoch"],
                    "assistantMessageId": call["assistant_message_id"],
                },
                image["versionId"],
            )
            artifact = media_tool_artifact(
                db, turn["owner_id"], turn["conversation_id"], turn["id"], image["artifactId"]
            )
            if not artifact or artifact["sha256"] != image["sha256"]:
                return None
            source = json.loads(artifact["metadata_json"])["mediaSource"]
            if (source["versionId"], source["artifactId"], source["sha256"]) != (
                image["versionId"],
                image["sourceArtifactId"],
                image["sourceSha256"],
            ):
                return None
            return {**artifact, "mediaToolCallId": message.get("tool_call_id")}

        try:
            source = await database.call(read)
        except DomainError:
            source = None
        if source:
            sources.append(source)
        else:
            unavailable.append(
                "Publication media sample unavailable; never claim to have inspected it: "
                + image["artifactId"]
            )
        if len(sources) == MAX_CONTEXT_IMAGES:
            break
    return sources, unavailable
