"""Mainstream input shapes execute without model-supplied bookkeeping."""

import json

import pytest
from test_foundations import call
from test_routing_policy import setup
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row
from roami_agent.tools.model_inputs import register_model_inputs


async def test_pi_file_inputs_read_lines_and_preserve_external_edits(store, tmp_path):
    runtime = Runtime(store, ConversationModel(), settings=Settings(shell_roots=(tmp_path,)))
    binding = {"owner": "alice", "workspace": {"directory": str(tmp_path)}}
    try:
        await runtime.tools.invoke(
            call("write", {"path": "note.txt", "content": "first\n第二行\nlast\n"}),
            "worker",
            binding,
        )
        read = await runtime.tools.invoke(
            call("read", {"path": "note.txt", "offset": 2, "limit": 1}), "worker", binding
        )
        assert read["data"] == "第二行\n" and read["nextOffset"] == 3
        await runtime.tools.invoke(
            call("edit", {"path": "note.txt", "oldText": "第二行", "newText": "changed"}),
            "worker",
            binding,
        )
        assert (tmp_path / "note.txt").read_text() == "first\nchanged\nlast\n"
        (tmp_path / "note.txt").write_text("User edits")
        with pytest.raises(DomainError, match="FILE_CHANGED"):
            await runtime.tools.invoke(
                call("write", {"path": "note.txt", "content": "Overwrite"}), "worker", binding
            )
        assert (tmp_path / "note.txt").read_text() == "User edits"
    finally:
        await runtime.close()


async def test_read_artifact_uses_same_line_range_as_file(store):
    runtime = Runtime(store, ConversationModel())
    try:
        item = await runtime.artifacts.put(
            "alice", b"first\nsecond\nthird\n", mime_type="text/plain", name="note.txt"
        )
        value = await runtime.tools.invoke(
            call("read", {"path": "artifact://" + item["id"], "offset": 2, "limit": 1}),
            "main",
            {"owner": "alice"},
        )
        assert value["text"] == "second\n" and value["nextOffset"] == 3
    finally:
        await runtime.close()


async def test_hash_is_recovered_from_durable_read_receipt(store, tmp_path):
    runtime, _, _, _, binding = await setup(
        store, settings=Settings(shell_roots=(tmp_path,), coding_directory=tmp_path)
    )
    binding = dict(binding, workspace={"directory": str(tmp_path)})
    turn = await store.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
    )
    path = tmp_path / "note.txt"
    path.write_text("original")
    try:
        reading = call("read", {"path": "note.txt"})
        reading["id"] = "read"
        read = await runtime.gateway.invoke(
            turn, binding["assistantMessageId"], reading, "main", binding
        )
        assert read["data"] == "original"
        runtime.files.observed.clear()
        path.write_text("human edit")
        writing = call("write", {"path": str(path), "content": "lost update"})
        writing["id"] = "write"
        result = await runtime.gateway.invoke(
            turn, binding["assistantMessageId"], writing, "main", binding
        )
        assert result["error"] == "FILE_CHANGED" and path.read_text() == "human edit"
    finally:
        await runtime.close()


async def test_bash_binds_main_context_and_registered_help_without_scope(store):
    runtime = Runtime(store, ConversationModel())
    try:
        value = await runtime.tools.invoke(
            call("bash", {"command": "printf 'compact-input'; pwd"}), "main", {"owner": "alice"}
        )
        assert value["exitCode"] == 0 and value["stdout"].startswith("compact-input/")
        assert not value["stdout"].strip().endswith(str(store.data_root))
        help_result = await runtime.tools.invoke(
            call("bash", {"command": "roami help"}), "main", {"owner": "alice"}
        )
        assert help_result["name"] == "roami"
        legacy = await runtime.tools.invoke(
            call("bash", {"argv": ["roami", "help"], "scope": "host"}), "main", {"owner": "alice"}
        )
        assert legacy["name"] == "roami"
        discovered = await runtime.tools.invoke(call("tool_list", {"query": "roami"}), "main", {})
        cli = next(item for item in discovered["items"] if item["kind"] == "cli")
        assert cli["command"] == "roami help" and "argv" not in cli
        assert all("command" in item and "argv" not in item for item in cli["commands"])
    finally:
        await runtime.close()


@pytest.mark.parametrize("executor", [None, "native", "codex"])
async def test_delegate_accepts_goal_and_optional_executor_without_routing(store, executor):
    runtime, _, _, registry, binding = await setup(store)
    register_model_inputs(registry)
    args = {"goal": "Prepare the requested report"}
    if executor:
        args["executor"] = executor
    try:
        result = await registry.invoke(call("delegate", args), "main", binding)
        assert result["acceptedOnly"] and result["executor"] == (executor or "claude")
        task = await store.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (result["taskId"],))
        )
        assert json.loads(task["intent_json"])["goal"] == args["goal"]
        assert result["routingDecision"]["reasonCode"] != "explicit_executor"
    finally:
        await runtime.close()


async def test_question_accepts_simple_choices_or_free_text_and_reply_needs_only_text(store):
    runtime = Runtime(store, ConversationModel())
    try:
        free = await runtime.tools.invoke(call("ask_user", {"prompt": "Which folder?"}), "main", {})
        assert free["question"]["options"] == []
        question = await runtime.tools.invoke(
            call("ask_user", {"prompt": "Which target?", "options": ["One", "Two"]}), "main", {}
        )
        assert question["question"]["options"] == [{"label": "One"}, {"label": "Two"}]
        reply = await runtime.tools.invoke(
            call("reply", {"text": "Requested raw field: stopConfirmed=false"}), "main", {}
        )
        assert reply["reply"] == "Requested raw field: stopConfirmed=false"
    finally:
        await runtime.close()


async def test_main_keeps_small_catalog_and_discovers_compact_task_commands(store):
    runtime = Runtime(store, ConversationModel())
    try:
        schemas = {
            t["function"]["name"]: t["function"]["parameters"] for t in runtime.tools.catalog()
        }
        assert schemas["bash"]["required"] == ["command"]
        assert schemas["write"]["required"] == ["path", "content"]
        assert schemas["edit"]["required"] == ["path", "oldText", "newText"]
        assert schemas["delegate"]["required"] == ["goal"]
        assert len(schemas) == 11
        assert not {"task_status", "task_steer", "task_cancel", "session_send"} & schemas.keys()
        commands = runtime.tools.directory.command_entries("main")[0]["commands"]
        schema = next(
            c["inputSchema"] for c in commands if c["argv"][1:4] == ["agent", "task", "steer"]
        )
        assert schema["required"] == ["taskId", "text"]
        exposed = json.dumps(schemas)
        for field in [
            "expectedSha256",
            "requestCoverage",
            "requestComplete",
            "routingExplanation",
            "scopeQuote",
        ]:
            assert field not in exposed
    finally:
        await runtime.close()


async def test_main_has_no_browser_or_desktop_tools_even_through_cli(store):
    from types import SimpleNamespace

    from roami_agent.tools.browser import register_browser_tools
    from roami_agent.tools.computer import register_computer_tools

    async def forbidden(*args, **kwargs):
        pytest.fail("Main started a browser or desktop action")

    runtime = Runtime(store, ConversationModel())
    driver = SimpleNamespace(open=forbidden, observe=forbidden, act=forbidden)
    register_browser_tools(runtime.tools, driver)
    register_computer_tools(runtime.tools, driver)
    register_model_inputs(runtime.tools)
    try:
        names = {tool["function"]["name"] for tool in runtime.tools.catalog("main")}
        assert len(names) == 11
        assert not any(name.startswith(("browser_", "computer_")) for name in names)
        discovered = runtime.tools.directory.operations("main")
        assert not any(tool.name.startswith(("browser_", "computer_")) for tool in discovered)
        for name in (
            "browser_open",
            "browser_observe",
            "browser_act",
            "computer_open",
            "computer_observe",
            "computer_act",
        ):
            with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
                await runtime.tools.invoke(call(name, {}), "main", {})
        with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
            await runtime.tools.invoke(
                call("bash", {"command": "roami chrome new https://example.com"}), "main", {}
            )
    finally:
        await runtime.close()


async def test_browser_commands_bind_returned_observation_without_id_parameters(store, monkeypatch):
    import shlex

    from test_browser_driver import BrowserFixture, BrowserModel, native_browser
    from test_runtime import until

    from roami_agent.protocol.models import ModelEvent

    original = BrowserModel.stream

    async def compact(self, messages, tools):
        async for part in original(self, messages, tools):
            if part.kind == "tool":
                value = part.value
                args = json.loads(value["function"]["arguments"])
                if value["function"]["name"] == "browser_open":
                    command = ["roami", "chrome", "new", args["url"]]
                else:
                    command = ["roami", "chrome", args["kind"], args["selector"]]
                    if "text" in args:
                        command.append(args["text"])
                yield ModelEvent(
                    "tool",
                    {
                        **value,
                        "function": {
                            "name": "bash",
                            "arguments": json.dumps({"command": shlex.join(command)}),
                        },
                    },
                )
            else:
                yield part

    monkeypatch.setattr(BrowserModel, "stream", compact)
    fixture = BrowserFixture()
    runtime, _, task = await native_browser(store, fixture)
    try:
        await until(
            store,
            lambda db: (
                row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))["state"] == "succeeded"
            ),
        )
        assert fixture.saved and fixture.name == "Roami"
        counts = await store.call(
            lambda db: row(
                db,
                "SELECT COUNT(*) n,SUM(state='failed') failed FROM tool_calls WHERE tool_name IN ('browser_open','browser_act')",
            )
        )
        assert counts == {"n": 3, "failed": 0}
    finally:
        await runtime.close()


async def test_computer_commands_bind_model_visible_screenshot_without_observation_id(
    store, monkeypatch
):
    import shlex

    pytest.importorskip("Xlib")
    from test_desktop_driver import DesktopModel, desktop
    from test_desktop_driver import (
        test_native_worker_computer_use_drives_real_x11_and_verifies_actual_form as verify_form,
    )

    from roami_agent.protocol.models import ModelEvent

    original = DesktopModel.stream

    async def compact(self, messages, tools):
        async for part in original(self, messages, tools):
            if part.kind == "tool":
                value = part.value
                args = json.loads(value["function"]["arguments"])
                args.pop("observationId", None)
                command = shlex.join(
                    [
                        "roami",
                        "agent",
                        "capability",
                        "call",
                        value["function"]["name"],
                        "--input",
                        json.dumps(args),
                    ]
                )
                yield ModelEvent(
                    "tool",
                    {
                        **value,
                        "function": {"name": "bash", "arguments": json.dumps({"command": command})},
                    },
                )
            else:
                yield part

    monkeypatch.setattr(DesktopModel, "stream", compact)
    display = desktop.__wrapped__()
    fixture = await anext(display)
    try:
        await verify_form(store, fixture)
    finally:
        await display.aclose()


async def test_task_continuation_binds_revision_without_model_repeating_it(store):
    runtime, _, _, registry, binding = await setup(store)
    register_model_inputs(registry)
    try:
        task = await registry.invoke(
            call("delegate", {"goal": "Write the report", "executor": "native"}), "main", binding
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE turns SET state='completed' WHERE id=?", (binding["turnId"],)
            ),
            write=True,
        )
        accepted = await runtime.conversations.accept(
            "alice", binding["conversation"], "followup", "Change the report title."
        )
        job = await store.call(
            lambda db: row(db, "SELECT * FROM jobs WHERE aggregate_id=?", (accepted["turnId"],))
        )
        turn = await runtime.mailbox.claim(job)
        mid = await runtime.journal.start(turn)
        next_binding = {
            **binding,
            "turnId": turn["id"],
            "originMessageId": accepted["messageId"],
            "assistantMessageId": mid,
            "toolCallId": "followup",
        }
        args = {"taskId": task["taskId"], "text": "Change the report title."}
        first = await registry.invoke(call("task_steer", args), "main", next_binding)
        assert first["acceptedOnly"] and first["revision"] == 1
        await store.call(
            lambda db: db.execute("UPDATE tasks SET revision=2 WHERE id=?", (task["taskId"],)),
            write=True,
        )
        repeated = await registry.invoke(call("task_steer", args), "main", next_binding)
        assert repeated == first
    finally:
        await runtime.close()
