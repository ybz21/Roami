"""Only the current task observation crosses an explicitly image-capable model route."""

import json

import httpx
import pytest
from test_resource_leases import controller
from test_runtime import ConversationModel
from vision_fixture import PNG

from roami_agent.app import Runtime
from roami_agent.context.vision_inputs import VisionInputs
from roami_agent.protocol.errors import DomainError
from roami_agent.providers.chat_completions import ChatCompletions
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row


@pytest.fixture
async def observation(store):
    runtime = Runtime(store, ConversationModel())
    try:
        task, run = await controller(store)
        artifact = await runtime.artifacts.put(
            "alice", PNG, mime_type="image/png", task_id=task, name="vision.png"
        )
        lease = await runtime.resources.claim("alice", task, run, "browser", "vision-fixture")
        observed = await runtime.resources.observe(
            "alice",
            lease["id"],
            task,
            run,
            lease["lease_epoch"],
            "a" * 64,
            {
                "screenshotRef": artifact["id"],
                "screenshot": {"width": 1, "height": 1, "scaleX": 1, "scaleY": 1},
            },
        )
        turn = {"id": "vision-turn", "owner_id": "alice", "executionRunId": run}
        prompt = [
            {"role": "system", "content": "Worker"},
            {"role": "user", "content": "Inspect the fixture"},
            {
                "role": "tool",
                "tool_call_id": "observe",
                "content": json.dumps({"observation": observed}),
            },
        ]
        yield runtime, turn, prompt, observed, artifact
    finally:
        await runtime.close()


async def test_only_active_bound_observation_is_attached_once(observation):
    runtime, turn, prompt, observed, artifact = observation
    vision = VisionInputs(runtime.db, runtime.artifacts)
    plan, attached = await vision.attach(turn, {"currentTurnStart": 0}, prompt)
    assert len(attached) == len(prompt) + 1
    image = attached[-1]["content"][1]["image_url"]["url"]
    assert image.startswith("data:image/png;base64,")
    assert plan["imageEvidence"][0]["artifactId"] == artifact["id"]
    assert plan["imageEvidence"][0]["observationId"] == observed["id"]
    assert "data:image" not in json.dumps(plan) and "data:image" not in json.dumps(prompt)
    for altered in [
        dict(turn, owner_id="bob"),
        dict(turn, executionRunId="other"),
        {"owner_id": "alice"},
    ]:
        assert (await vision.attach(altered, {}, prompt))[1] == prompt
    await runtime.db.call(
        lambda db: db.execute("UPDATE resources SET scene_epoch=scene_epoch+1"), write=True
    )
    assert (await vision.attach(turn, {}, prompt))[1] == prompt


async def test_oversized_image_never_becomes_model_payload(observation):
    runtime, turn, prompt, _, _ = observation
    vision = VisionInputs(runtime.db, runtime.artifacts)
    vision.max_bytes = 1
    plan, attached = await vision.attach(turn, {}, prompt)
    assert plan["imageError"] == "VISION_IMAGE_LIMIT" and not plan["imageEvidence"]
    assert "data:image" not in json.dumps(attached)


async def test_revoked_image_manifest_prevents_further_model_and_tool_admission(observation):
    runtime, turn, prompt, _, artifact = observation
    plan, _ = await VisionInputs(runtime.db, runtime.artifacts).attach(turn, {}, prompt)
    task_run = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE id=?", (turn["executionRunId"],))
    )
    branch = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM branches WHERE id=?", (task_run["native_branch_id"],))
    )
    turn.update(conversation_id=branch["conversation_id"], branch_id=branch["id"])
    await runtime.db.call(
        lambda db: db.execute(
            "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms) VALUES(?,?,?,'user','running',1)",
            (turn["id"], turn["conversation_id"], turn["branch_id"]),
        ),
        write=True,
    )
    await runtime.manifests.record(
        turn, 1, "vision-model", "a" * 64, {**plan, "snapshotId": None}, [], "worker"
    )
    await runtime.db.call(lambda db: assert_context_admitted(db, turn))
    await runtime.artifacts.delete("alice", artifact["id"])
    with pytest.raises(DomainError, match="CONTEXT_SOURCE_FORGOTTEN"):
        await runtime.db.call(lambda db: assert_context_admitted(db, turn))


async def test_provider_rejects_images_before_network_without_explicit_capability():
    async def unexpected(request):
        pytest.fail("An undeclared image capability reached the network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        provider = ChatCompletions(
            "https://provider.example/v1", "text-only", "fixture", client=client
        )
        with pytest.raises(DomainError, match="MODEL_IMAGES_UNSUPPORTED"):
            async for _ in provider.stream(
                [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,fixture"},
                            }
                        ],
                    }
                ],
                [],
            ):
                pass


async def test_image_capable_provider_preserves_multimodal_payload():
    payloads = []

    async def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"choices":[{"delta":{"content":"Observed"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Read this image"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,fixture"}},
            ],
        }
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = ChatCompletions(
            "https://provider.example/v1",
            "vision",
            "fixture",
            client=client,
            capabilities={"images": True},
        )
        events = [event async for event in provider.stream(messages, [])]
    assert payloads[0]["messages"] == messages
    assert any(event.kind == "text" and event.value == "Observed" for event in events)
