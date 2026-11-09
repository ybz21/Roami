import base64
import io
import json

import pytest
from PIL import Image
from test_publication_media_inspection import Decoder
from test_publication_media_scope import media_fixture
from test_publication_media_speech import AudioDecoder, Speech
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.dispatch.publication_media import PublicationMedia
from roami_agent.protocol.identity import identity
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import message
from roami_agent.tools.publication_media_catalog import register_publication_media_tools

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def media_inputs(
    fixture, *, audio=False, transcript="Final source speech", account=None, source_mime="video/mp4"
):
    runtime = fixture[0]
    runtime.settings.model_capabilities["images"] = True
    runtime, binding, scope, version, media, _ = await media_fixture(
        fixture, account=account, source_mime=source_mime
    )
    runtime.tools.registry.pop("swarm_publication_media")
    register_publication_media_tools(
        runtime.tools,
        runtime.db,
        runtime.artifacts,
        lambda: PublicationMedia(
            runtime.db,
            runtime.artifacts,
            AudioDecoder() if audio else Decoder(),
            Speech(text=transcript) if audio else None,
        ),
    )
    turn = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM turns WHERE id=?", (binding["turnId"],))
    )
    turn["owner_id"] = "alice"
    binding["originMessageId"] = await runtime.db.call(
        lambda db: db.execute(
            "SELECT source_message_id FROM swarm_goal_delegations WHERE id=?",
            (scope["delegationId"],),
        ).fetchone()[0]
    )

    async def invoke(operation, artifact_id):
        args = {
            "swarmId": scope["swarmId"],
            "versionId": version["versionId"],
            "operation": operation,
            "artifactId": artifact_id,
        }
        call = {
            "id": identity(),
            "type": "function",
            "function": {
                "name": "bash",
                "arguments": json.dumps(
                    {
                        "argv": [
                            "roami",
                            "swarm",
                            "publication",
                            "media",
                            "--input",
                            json.dumps(args),
                        ]
                    }
                ),
            },
        }
        if operation == "read":
            call["function"] = {
                "name": "read",
                "arguments": json.dumps({"path": "artifact://" + artifact_id}),
            }
        mid = await runtime.db.call(
            lambda db: message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "assistant",
                {"text": "", "tool_calls": [call]},
                turn_id=turn["id"],
            ),
            write=True,
        )
        value = await runtime.gateway.invoke(
            turn,
            mid,
            call,
            "main",
            {**binding, "assistantMessageId": mid, "toolCallId": call["id"]},
        )
        return value, {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(value)}

    inspected, _ = await invoke("inspect", media["id"])
    return runtime, turn, inspected, invoke, binding


async def test_registered_media_read_delivers_real_sample_pixels_to_main(coordination):
    runtime, turn, inspected, invoke, _ = await media_inputs(coordination)
    tools = []
    for image in inspected["images"]:
        value, tool = await invoke("image", image["id"])
        assert value["mediaImage"]["artifactId"] == image["id"]
        tools.append(tool)
    plan, prompt = await runtime.loop.context.chat_images.attach(
        turn,
        {"currentTurnStart": 0},
        [
            {"role": "system", "content": "Main"},
            {"role": "user", "content": "Review final media"},
            *tools,
        ],
    )
    assert len(plan["imageEvidence"]) == 3
    assert all(item["source"] == "publication_media" for item in plan["imageEvidence"])
    assert all(item["versionId"] == inspected["versionId"] for item in plan["imageEvidence"])
    pictures = [
        part
        for msg in prompt
        if isinstance(msg.get("content"), list)
        for part in msg["content"]
        if part.get("type") == "image_url"
    ]
    assert len(pictures) == 3
    for part in pictures:
        with Image.open(
            io.BytesIO(base64.b64decode(part["image_url"]["url"].split(",", 1)[1]))
        ) as image:
            red, green, blue = image.convert("RGB").getpixel(
                (image.width // 6, int(image.height * 320 / 1328))
            )
            assert red > 200 and green < 40 and blue < 40
    assert inspected["publicationAuthorized"] is False


@pytest.mark.parametrize(
    "fault", ["forged_call", "old_lease", "unknown_version", "forgotten_source"]
)
async def test_media_metadata_and_fake_reads_do_not_become_image_evidence(coordination, fault):
    runtime, turn, inspected, invoke, _ = await media_inputs(coordination)
    _, tool = await invoke("image", inspected["images"][0]["id"])
    if fault == "forged_call":
        tool["tool_call_id"] = "never-invoked"
    elif fault == "old_lease":
        turn["lease_epoch"] += 1
    elif fault == "unknown_version":
        value = json.loads(tool["content"])
        value["mediaImage"]["versionId"] = "other-version"
        tool["content"] = json.dumps(value)
    else:
        await runtime.db.call(
            lambda db: db.execute(
                "INSERT INTO memory_tombstones VALUES(?,?,?,1)",
                ("alice", inspected["sourceSha256"], "forgotten-media"),
            ),
            write=True,
        )
    plan, _ = await runtime.loop.context.chat_images.attach(
        turn,
        {"currentTurnStart": 0},
        [{"role": "system", "content": "Main"}, {"role": "user", "content": "Review"}, tool],
    )
    assert not plan.get("imageEvidence")
