"""Saved image availability reaches planning before a role handoff."""

import pytest
from test_main_file_image_inputs import ReadImage, picture

from roami_agent.app import Runtime
from roami_agent.context.token_estimate import request_basis
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


def configuration(runtime, role):
    turn = {} if role == "main" else {"executionRunId": "native-attempt"}
    return runtime.loop.context._configuration(turn, "Saved policy", runtime.tools.catalog(role))


@pytest.mark.parametrize(
    "main,worker", [(True, False), (False, True), (True, True), (False, False)]
)
@pytest.mark.parametrize("role", ["main", "worker"])
async def test_saved_role_availability_precedes_handoff(store, main, worker, role):
    runtime = Runtime(
        store,
        ReadImage("unused"),
        settings=Settings(endpoint="http://127.0.0.1:1/v1", model="role-availability-fixture"),
    )
    runtime.model_settings.factory = lambda settings, role: ReadImage("unused")
    try:
        await runtime.model_settings.save(
            "local", {"main": {"images": main}, "worker": {"images": worker}}
        )
        result = configuration(runtime, role)
        instructions = result["instructions"]
        assert instructions.startswith("Saved policy")
        assert f"Main={'enabled' if main else 'disabled'}" in instructions
        assert f"Worker={'enabled' if worker else 'disabled'}" in instructions
        assert f"Current role: {role}" in instructions
        assert "handoff does not transfer" in instructions
        assert "role-availability-fixture" not in instructions
        assert "127.0.0.1" not in instructions
    finally:
        await runtime.close()


async def test_worker_setting_changes_main_context_basis_without_changing_saved_policy(store):
    runtime = Runtime(
        store,
        ReadImage("unused"),
        settings=Settings(
            endpoint="http://127.0.0.1:1/v1",
            model="role-availability-fixture",
            main_instructions="Saved policy",
        ),
    )
    runtime.model_settings.factory = lambda settings, role: ReadImage("unused")
    try:
        await runtime.model_settings.save(
            "local", {"main": {"images": True}, "worker": {"images": False}}
        )
        initial = configuration(runtime, "main")
        assert runtime.context.request_context() == initial
        await runtime.model_settings.save("local", {"worker": {"images": True}})
        active = configuration(runtime, "main")
        assert initial["route"] == active["route"]
        assert request_basis(initial) != request_basis(active)
        assert runtime.context.request_context() == active
        await runtime.model_settings.save("local", {"worker": {"images": False}})
        assert configuration(runtime, "main") == initial
        assert runtime.settings.main_instructions == "Saved policy"
    finally:
        await runtime.close()


async def test_actual_main_provider_gets_saved_roles_and_file_pixels(store, tmp_path):
    path = tmp_path / "frame.png"
    path.write_bytes(picture())

    class InspectRoles(ReadImage):
        async def stream(self, messages, tools):
            policy = messages[0]["content"]
            assert "Main=enabled; Worker=disabled" in policy
            assert "Current role: main" in policy
            async for event in super().stream(messages, tools):
                yield event

    model = InspectRoles(path)
    runtime = Runtime(
        store,
        model,
        settings=Settings(
            endpoint="http://127.0.0.1:1/v1",
            model="role-availability-fixture",
            shell_roots=[tmp_path],
        ),
    )
    runtime.model_settings.factory = lambda settings, role: (
        model if role == "main" else ReadImage(path)
    )
    try:
        await runtime.model_settings.save(
            "local", {"main": {"images": True}, "worker": {"images": False}}
        )
        conversation = await runtime.conversations.create("local")
        await runtime.chat.submit(
            "local", conversation["id"], "role-aware-read", "Read " + str(path)
        )
        job = await store.call(lambda db: row(db, "SELECT * FROM jobs WHERE kind='turn.run'"))
        turn = await runtime.mailbox.claim(job)
        assert await runtime.loop.run(turn, "main") == "Image observed."
        assert model.calls == 2 and len(model.pixels) == 1
    finally:
        await runtime.close()
