"""Native Workers use observed, scoped browser actions without occupying Main capacity."""

import asyncio
import base64
import hashlib
import json
from pathlib import Path

import pytest

from roami_agent.app import Runtime
from roami_agent.executors.browser_driver import BrowserDriver
from roami_agent.protocol.browser import browser_config
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.serialization import encoded
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row, rows

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)


class BrowserFixture:
    def __init__(self):
        self.name = ""
        self.saved = False
        self.url = "about:blank"
        self.writes = []
        self.receipts = {}
        self.block_click = False
        self.started = asyncio.Event()
        self.gate = asyncio.Event()
        self.stop_known = True

    def scene(self):
        return {
            "url": self.url,
            "title": "Fixture",
            "domText": "Saved" if self.saved else "Name form",
            "controls": [
                {"selector": "#name", "value": self.name},
                {"selector": "#save", "text": "Save"},
            ],
            "viewportSize": {"width": 1, "height": 1},
            "deviceScale": 1,
            "signature": hashlib.sha256(
                encoded([self.url, self.name, self.saved]).encode()
            ).hexdigest(),
        }

    @staticmethod
    def arguments(argv):
        flags, positionals, index = {}, [], 3
        while index < len(argv):
            value = argv[index]
            if value.startswith("--"):
                if value in {"--no-retry", "--no-focus"}:
                    flags[value] = True
                else:
                    index += 1
                    flags[value] = argv[index]
            else:
                positionals.append(value)
            index += 1
        return argv[2], flags, positionals

    async def __call__(self, argv, **options):
        assert "ROAMI_AGENT_API_KEY" not in options["env"]
        verb, flags, args = self.arguments(argv)
        assert flags["--no-focus"]
        operation_id = flags.get("--operation-id")
        if verb == "capabilities":
            output = {
                "browserId": "browser-fixture",
                "features": [
                    "target_id",
                    "operation_receipts",
                    "scene_observation",
                    "expected_scene",
                ],
            }
        elif verb in {"operation-cancel", "operation-status"}:
            output = self.receipts[operation_id]
            if self.stop_known and verb == "operation-cancel":
                output.update(state="cancelled", inputStopped=True, outcomeKnown=True)
                self.gate.set()
        elif verb == "observe":
            output = self.scene()
            if "--screenshot" in flags:
                Path(flags["--screenshot"]).write_bytes(PNG)
                output["screenshot"] = {
                    "path": flags["--screenshot"],
                    "width": 1,
                    "height": 1,
                    "scaleX": 1,
                    "scaleY": 1,
                }
        else:
            output = {
                "version": 1,
                "id": operation_id,
                "payloadHash": "a" * 64,
                "state": "running",
                "inputStopped": False,
                "outcomeKnown": False,
            }
            self.receipts[operation_id] = output
            assert flags["--expected-browser"] == "browser-fixture"
            if verb != "new" and flags["--expected-scene"] != self.scene()["signature"]:
                output.update(
                    state="failed",
                    inputStopped=True,
                    outcomeKnown=True,
                    errorCode="CHROME_SCENE_CHANGED",
                )
            else:
                if verb == "click" and self.block_click:
                    self.started.set()
                    await self.gate.wait()
                self.writes.append(verb)
                if verb == "new":
                    assert args == []
                    body = encoded({"targetId": "target-fixture", "url": self.url})
                else:
                    if verb == "goto":
                        self.url = args[0]
                    if verb == "fill":
                        self.name = args[1]
                    if verb == "click":
                        self.saved = True
                    body = "ok"
                output.update(
                    state="succeeded", inputStopped=True, outcomeKnown=True, result={"stdout": body}
                )
        return {"exitCode": 0, "stdout": encoded(output), "stderr": ""}


class BrowserModel:
    model = "browser-fixture-model"

    def __init__(self):
        self.step = 0

    async def stream(self, messages, tools):
        if not tools or "ask_user" in {item["function"]["name"] for item in tools}:
            yield ModelEvent("text", "Reported in the original conversation")
            return
        self.step += 1
        if self.step == 1:
            name, args = "browser_open", {"url": "https://fixture.example/form"}
        else:
            result = json.loads(messages[-1]["content"])
            if self.step == 2:
                name, args = (
                    "browser_act",
                    {
                        "observationId": result["observation"]["id"],
                        "kind": "fill",
                        "selector": "#name",
                        "text": "Roami",
                    },
                )
            elif self.step == 3:
                name, args = (
                    "browser_act",
                    {
                        "observationId": result["observation"]["id"],
                        "kind": "click",
                        "selector": "#save",
                    },
                )
            else:
                assert result["observation"]["domText"] == "Saved"
                yield ModelEvent(
                    "text", "The fixture saved Roami; screenshot evidence is attached to the task."
                )
                return
        yield ModelEvent(
            "tool",
            {
                "id": "browser-" + str(self.step),
                "type": "function",
                "function": {"name": name, "arguments": encoded(args)},
            },
        )


async def native_browser(store, fixture, *, workers=1, runner=None):
    model = BrowserModel()

    async def verify(task, result):
        return fixture.saved and fixture.name == "Roami"

    runtime = Runtime(
        store,
        model,
        worker_model=model,
        settings=Settings(browser={"enabled": True}, workers=workers),
        verifier=verify,
    )
    runtime.browser.runner = runner or fixture

    async def receipt_reader(operation_id):
        return fixture.receipts[operation_id]

    runtime.browser.receipt_reader = receipt_reader
    await runtime.start()
    conversation = await runtime.conversations.create("alice")
    task = await runtime.tasks.create(
        "alice",
        conversation["id"],
        "Save Roami in the browser form",
        key="browser-task",
        record_intent=True,
    )
    runtime.wakeup.set()
    return runtime, conversation, task


@pytest.mark.parametrize("navigation_guard", [False, True])
async def test_native_worker_uses_real_task_scope_and_verifies_independent_browser_state(
    store, monkeypatch, navigation_guard
):
    from test_runtime import until

    monkeypatch.setenv("ROAMI_AGENT_API_KEY", "must-not-inherit")
    fixture = BrowserFixture()
    if navigation_guard:
        original_scene = fixture.scene
        original_run = fixture.__call__

        def scene():
            return {**original_scene(), "navigationSignature": "b" * 64}

        async def run(argv, **options):
            verb, flags, _ = fixture.arguments(argv)
            if verb == "goto":
                assert flags["--expected-scene"] == "b" * 64
                argv = list(argv)
                argv[argv.index("--expected-scene") + 1] = original_scene()["signature"]
            elif verb in {"fill", "click"}:
                assert flags["--expected-scene"] == original_scene()["signature"]
            return await original_run(argv, **options)

        fixture.scene = scene
        runner = run
    else:
        runner = fixture
    runtime, conversation, task = await native_browser(store, fixture, runner=runner)
    try:
        await until(
            store,
            lambda db: (
                row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))["state"] == "succeeded"
            ),
        )
        assert fixture.writes == ["new", "goto", "fill", "click"]
        result = await store.call(
            lambda db: row(
                db, "SELECT result_json FROM task_attempts WHERE task_id=?", (task["id"],)
            )
        )
        assert not json.loads(result["result_json"]).get("artifactRefs")
        actions = await store.call(
            lambda db: rows(db, "SELECT * FROM resource_actions WHERE task_id=?", (task["id"],))
        )
        assert len(actions) == 4 and all(action["state"] == "succeeded" for action in actions)
        assert not await store.call(
            lambda db: row(db, "SELECT id FROM resources WHERE owner_task_id=?", (task["id"],))
        )
        artifacts = await runtime.artifacts.list("alice", task_id=task["id"])
        assert len(artifacts) == 4 and all(item["messageId"] for item in artifacts)
        assert (await runtime.artifacts.read("alice", artifacts[0]["id"]))[1] == PNG
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM messages WHERE conversation_id=? AND role='assistant' AND status='completed'",
                (conversation["id"],),
            ),
        )
    finally:
        await runtime.close()


@pytest.mark.parametrize("initial_failure", [False, True])
async def test_failed_source_navigation_can_continue_in_the_same_task(store, initial_failure):
    from test_runtime import until

    fixture = BrowserFixture()

    async def runner(argv, **options):
        verb, _, args = fixture.arguments(argv)
        result = await fixture(argv, **options)
        if verb == "goto" and args[0] == "https://unreachable.example/":
            receipt = json.loads(result["stdout"])
            receipt.update(
                state="failed",
                inputStopped=True,
                outcomeKnown=True,
                errorCode="CHROME_NAVIGATION_CONNECTION_TIMED_OUT",
                result={"stdout": ""},
            )
            fixture.receipts[receipt["id"]] = receipt
            fixture.url = "chrome-error://chromewebdata/"
            result["stdout"] = encoded(receipt)
        return result

    class RecoveryModel(BrowserModel):
        async def stream(self, messages, tools):
            if not tools or "ask_user" in {item["function"]["name"] for item in tools}:
                yield ModelEvent("text", "Reported in the original conversation")
                return
            self.step += 1
            result = json.loads(messages[-1]["content"]) if self.step > 1 else {}
            if initial_failure and self.step == 2:
                assert result["navigationFailed"] and result["opened"]
                self.resource = result["resourceId"]
            phase = self.step + int(initial_failure and self.step > 1)
            if phase == 1:
                name, args = (
                    "browser_open",
                    ({"url": "https://unreachable.example/"} if initial_failure else {}),
                )
            elif phase == 2:
                self.resource = result["observation"]["resourceId"]
                name, args = (
                    "browser_act",
                    {
                        "kind": "goto",
                        "observationId": result["observation"]["id"],
                        "url": "https://unreachable.example/",
                    },
                )
            elif phase == 3:
                assert result["error"] == "CHROME_NAVIGATION_CONNECTION_TIMED_OUT"
                assert not result.get("retryable")
                name, args = "browser_observe", {"resourceId": self.resource}
            elif phase == 4:
                name, args = (
                    "browser_act",
                    {
                        "kind": "goto",
                        "observationId": result["observation"]["id"],
                        "url": "https://fixture.example/alternative",
                    },
                )
            else:
                assert result["observation"]["url"] == "https://fixture.example/alternative"
                yield ModelEvent("text", "Alternative source retrieved successfully.")
                return
            yield ModelEvent(
                "tool",
                {
                    "id": "recovery-" + str(self.step),
                    "type": "function",
                    "function": {"name": name, "arguments": encoded(args)},
                },
            )

    model = RecoveryModel()

    async def verify(task, result):
        return fixture.url == "https://fixture.example/alternative"

    runtime = Runtime(
        store,
        model,
        worker_model=model,
        settings=Settings(browser={"enabled": True}),
        verifier=verify,
    )
    runtime.browser.runner = runner
    runtime.browser.receipt_reader = lambda operation_id: asyncio.sleep(
        0, result=fixture.receipts[operation_id]
    )
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Find an accessible source",
            key="source",
            record_intent=True,
        )
        runtime.wakeup.set()
        await until(
            store,
            lambda db: (
                row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))["state"] == "succeeded"
            ),
        )
        assert (
            await store.call(lambda db: db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]) == 1
        )
        assert fixture.writes.count("new") == 1
        assert (
            await store.call(
                lambda db: db.execute(
                    "SELECT COUNT(*) FROM tool_calls WHERE state='unknown'"
                ).fetchone()[0]
            )
            == 0
        )
    finally:
        await runtime.close()


@pytest.mark.parametrize("known, expected", [(True, "cancelled"), (False, "interrupted")])
async def test_browser_cancel_requires_actual_driver_stop_evidence(store, known, expected):
    from test_runtime import until

    fixture = BrowserFixture()
    fixture.block_click, fixture.stop_known = True, known
    runtime, _, task = await native_browser(store, fixture)
    try:
        async with asyncio.timeout(5):
            await fixture.started.wait()
        await runtime.tasks.cancel("alice", task["id"])
        runtime.wakeup.set()
        await until(
            store,
            lambda db: (
                row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))["state"] == expected
            ),
        )
        assert "click" not in fixture.writes
        held = await store.call(
            lambda db: rows(db, "SELECT * FROM resources WHERE owner_task_id=?", (task["id"],))
        )
        assert bool(held) is (not known)
        if held:
            assert all(item["state"] == "quarantined" for item in held)
    finally:
        await runtime.close()


async def test_browser_wait_does_not_consume_main_answer_capacity(store):
    from test_runtime import until

    fixture = BrowserFixture()
    fixture.block_click = True
    runtime, _, _ = await native_browser(store, fixture)
    try:
        async with asyncio.timeout(5):
            await fixture.started.wait()
        conversation = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit(
            "alice", conversation["id"], "quick-answer", "Reply while the browser is busy"
        )
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
            timeout=1,
        )
    finally:
        await runtime.close()


async def test_disabled_browser_never_expands_main_or_worker_catalog(store):
    runtime = Runtime(store, BrowserModel())
    try:
        assert not any(
            item["function"]["name"].startswith("browser_")
            for item in runtime.tools.catalog("worker")
        )
        assert not any(
            item["function"]["name"].startswith("browser_")
            for item in runtime.tools.catalog("main")
        )
    finally:
        await runtime.close()


async def test_unavailable_background_screenshot_keeps_fresh_dom_and_never_repeats_input(store):
    from test_runtime import until

    fixture = BrowserFixture()
    runtime, _, task = await native_browser(store, fixture)

    async def runner(argv, **options):
        assert options["timeout"] is None
        if argv[2] == "observe" and "--screenshot" in argv:
            assert argv[argv.index("--timeout") + 1] == "5000"
            return {"exitCode": 1, "stdout": "", "stderr": "CHROME_OBSERVATION_TIMEOUT"}
        assert argv[argv.index("--timeout") + 1] == ("5000" if argv[2] == "observe" else "0")
        return await fixture(argv, **options)

    runtime.browser.runner = runner
    try:
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM tasks WHERE id=? AND state='succeeded'", (task["id"],)
            ),
        )
        assert fixture.writes == ["new", "goto", "fill", "click"]
        assert not await runtime.artifacts.list("alice", task_id=task["id"])
        observations = await store.call(
            lambda db: rows(
                db,
                "SELECT body_json FROM resource_observations WHERE json_extract(body_json,'$.screenshotError') IS NOT NULL",
            )
        )
        assert len(observations) == 4
        assert all("screenshotRef" not in json.loads(item["body_json"]) for item in observations)
    finally:
        await runtime.close()


async def test_late_browser_receipt_releases_control_without_promoting_interrupted_task(store):
    from test_runtime import until

    fixture = BrowserFixture()
    fixture.block_click, fixture.stop_known = True, False
    runtime, _, task = await native_browser(store, fixture)
    try:
        await asyncio.wait_for(fixture.started.wait(), 5)
        await runtime.tasks.cancel("alice", task["id"])
        runtime.wakeup.set()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM tasks WHERE id=? AND state='interrupted'", (task["id"],)
            ),
        )
        action = await store.call(
            lambda db: row(db, "SELECT id FROM resource_actions WHERE state='unknown'")
        )
        fixture.receipts[action["id"]].update(
            state="succeeded", inputStopped=True, outcomeKnown=True, result={"stdout": "ok"}
        )
        await runtime.browser.reconcile()
        assert not await store.call(
            lambda db: row(db, "SELECT id FROM resources WHERE owner_task_id=?", (task["id"],))
        )
        assert (
            await store.call(
                lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))
            )
        )["state"] == "interrupted"
        assert "click" not in fixture.writes
        events = await store.call(
            lambda db: rows(db, "SELECT * FROM events WHERE kind='task.resource_reconciled'")
        )
        assert len(events) == 1
        await runtime.browser.reconcile()
        assert fixture.writes == ["new", "goto", "fill"]
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update(controls="invalid"),
        lambda body: body.update(signature="invalid"),
        lambda body: body.update(navigationSignature=None),
        lambda body: body.update(navigationSignature="invalid"),
        lambda body: body["screenshot"].update(scaleX=float("nan")),
        lambda body: body["screenshot"].update(width=True),
        lambda body: body["screenshot"].update(path="/foreign/file.png"),
    ],
)
def test_invalid_observation_cannot_supply_scene_or_coordinate_evidence(mutate):
    body = BrowserFixture().scene()
    body["screenshot"] = {"path": "/capture.png", "width": 1, "height": 1, "scaleX": 1, "scaleY": 1}
    mutate(body)
    with pytest.raises(DomainError):
        BrowserDriver._observation(body, Path("/capture.png"))


@pytest.mark.parametrize(
    "state, stopped, known",
    [("succeeded", False, True), ("running", True, False), ("unknown", True, True)],
)
def test_malformed_driver_acknowledgements_cannot_prove_inputs_stopped(state, stopped, known):
    with pytest.raises(DomainError, match="BROWSER_DRIVER_PROTOCOL_INVALID"):
        BrowserDriver._receipt(
            {
                "version": 1,
                "id": "a" * 32,
                "payloadHash": "a" * 64,
                "state": state,
                "inputStopped": stopped,
                "outcomeKnown": known,
            },
            "a" * 32,
        )


@pytest.mark.parametrize(
    "config",
    [
        {"enabled": "yes"},
        {"max_tabs": True},
        {"max_tabs": -1},
        {"max_tabs": 1.5},
        {"existing_tabs": 1},
        {"unknown": True},
    ],
)
def test_browser_configuration_rejects_invalid_values(config):
    with pytest.raises(DomainError, match="INVALID_BROWSER_CONFIG"):
        browser_config(config)


@pytest.mark.parametrize("budget", [0, 1, 7, 100])
def test_browser_budget_is_optional_and_has_no_fixed_ceiling(budget):
    assert browser_config({"max_tabs": budget})["max_tabs"] == budget
    assert browser_config({"enabled": True})["max_tabs"] == 0


async def test_unlimited_tabs_and_durable_observation_failure_do_not_weaken_ownership(store):
    from test_runtime import ConversationModel, until

    fixture, failed, target_count, observations = BrowserFixture(), False, 0, 0

    async def runner(argv, **options):
        nonlocal target_count, observations
        verb, flags, _ = fixture.arguments(argv)
        if verb == "observe":
            observations += 1
            if failed:
                raise DomainError("BROWSER_DRIVER_UNAVAILABLE", 503)
        result = await fixture(argv, **options)
        if verb == "new":
            target_count += 1
            receipt = fixture.receipts[flags["--operation-id"]]
            receipt["result"]["stdout"] = encoded({"targetId": "target-" + str(target_count)})
            result["stdout"] = encoded(receipt)
        return result

    class Worker:
        model = "browser-recovery"

        async def stream(self, messages, tools):
            nonlocal failed
            attempt = await store.call(
                lambda db: row(db, "SELECT * FROM task_attempts WHERE state='running'")
            )
            turn = await store.call(
                lambda db: row(
                    db,
                    "SELECT * FROM turns WHERE branch_id=? AND state='running'",
                    (attempt["native_branch_id"],),
                )
            )
            binding = {
                "owner": "alice",
                "conversation": turn["conversation_id"],
                "turnId": turn["id"],
                "taskId": attempt["task_id"],
                "runId": attempt["id"],
                "role": "research",
                "toolCallId": "setup",
            }
            opened = [
                await runtime.browser.open({}, dict(binding, toolCallId=str(i))) for i in range(5)
            ]
            assert target_count == 5
            resource_id = opened[0]["observation"]["resourceId"]
            runtime.browser.config["max_tabs"] = 5
            with pytest.raises(DomainError, match="BROWSER_TAB_BUDGET_EXCEEDED"):
                await runtime.browser.open({}, binding)
            runtime.browser.config["max_tabs"] = 0
            failed = True
            with pytest.raises(DomainError, match="BROWSER_DRIVER_UNAVAILABLE"):
                await runtime.browser.observe({"resourceId": resource_id}, binding)
            count = observations
            # A restarted driver must retain the same failed-scene fence.
            runtime.browser = BrowserDriver(
                store, runtime.settings, runtime.resources, runtime.artifacts, runner=runner
            )
            with pytest.raises(DomainError, match="BROWSER_SOURCE_UNAVAILABLE"):
                await runtime.browser.observe({"resourceId": resource_id}, binding)
            assert observations == count
            with pytest.raises(DomainError, match="RESOURCE_TASK_NOT_FOUND"):
                await runtime.browser.observe(
                    {"resourceId": resource_id}, dict(binding, owner="mallory")
                )
            failed = False
            assert await runtime.browser.open({}, dict(binding, toolCallId="alternate"))
            await store.call(
                lambda db: db.execute(
                    "UPDATE resources SET scene_epoch=scene_epoch+1 WHERE id=?", (resource_id,)
                ),
                write=True,
            )
            assert await runtime.browser.observe({"resourceId": resource_id}, binding)
            await store.call(
                lambda db: db.execute(
                    "UPDATE resources SET state='paused' WHERE id=?", (resource_id,)
                ),
                write=True,
            )
            with pytest.raises(DomainError, match="RESOURCE_INPUT_PAUSED"):
                await runtime.browser.observe({"resourceId": resource_id}, binding)
            yield ModelEvent("text", "Available source read; unavailable source omitted.")

    runtime = Runtime(
        store,
        ConversationModel(),
        worker_model=Worker(),
        settings=Settings(browser={"enabled": True}),
    )
    runtime.browser.runner = runner
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            c["id"],
            "Read public sources",
            key="research",
            target={"kind": "new_session", "resourceOnly": True},
            record_intent=True,
        )
        await runtime.start()
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM task_attempts WHERE task_id=? AND finished_ms IS NOT NULL",
                (task["id"],),
            ),
        )
        assert target_count == 6
        failures = await store.call(
            lambda db: rows(db, "SELECT * FROM events WHERE kind='resource.observation_failed'")
        )
        assert len(failures) == 1
    finally:
        await runtime.close()


@pytest.mark.parametrize("resource_only,stopped", [(True, True), (True, False), (False, True)])
async def test_only_stopped_research_navigation_returns_fresh_scene_without_replaying_input(
    store, resource_only, stopped
):
    from test_runtime import ConversationModel, until

    class ResearchModel:
        model = "stopped-navigation-research"

        def __init__(self):
            self.steps = 0

        async def stream(self, messages, tools):
            self.steps += 1
            if self.steps == 1:
                name, args = "browser_open", {}
            else:
                value = json.loads(messages[-1]["content"])
                if self.steps == 3:
                    assert value["navigationRecoveryAvailable"] is True
                    assert value["action"]["state"] == "unknown"
                    assert value["action"]["outcomeKnown"] is False
                    assert value["action"]["inputStopped"] is True
                if self.steps == 4:
                    assert value["observation"]["url"] == "https://fixture.example/alternate"
                    yield ModelEvent("text", "Retrieved https://fixture.example/alternate")
                    return
                name, args = (
                    "browser_act",
                    {
                        "observationId": value["observation"]["id"],
                        "kind": "goto",
                        "url": "https://fixture.example/pricing"
                        if self.steps == 2
                        else "https://fixture.example/alternate",
                    },
                )
            yield ModelEvent(
                "tool",
                {"id": str(self.steps), "function": {"name": name, "arguments": encoded(args)}},
            )

    fixture, model = BrowserFixture(), ResearchModel()
    fixture.stop_known = False
    navigation_count = 0

    async def runner(argv, **options):
        nonlocal navigation_count
        result = await fixture(argv, **options)
        verb, flags, _ = fixture.arguments(argv)
        if verb == "goto":
            assert flags["--timeout"] == ("15000" if resource_only else "0")
            navigation_count += 1
            if navigation_count == 1:
                receipt = fixture.receipts[flags["--operation-id"]]
                receipt.update(state="unknown", inputStopped=stopped, outcomeKnown=False)
                result["stdout"] = encoded(receipt)
        return result

    runtime = Runtime(
        store, ConversationModel(), worker_model=model, settings=Settings(browser={"enabled": True})
    )
    runtime.browser.runner = runner
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            c["id"],
            "Check source",
            key="lookup",
            target={"kind": "new_session", **({"resourceOnly": True} if resource_only else {})},
            record_intent=True,
        )
        runtime.wakeup.set()
        state = "succeeded" if resource_only and stopped else "interrupted"
        await until(
            store,
            lambda db: row(db, "SELECT id FROM tasks WHERE id=? AND state=?", (task["id"], state)),
        )
        assert fixture.writes == (
            ["new", "goto", "goto"] if state == "succeeded" else ["new", "goto"]
        )
        assert await store.call(
            lambda db: row(
                db,
                "SELECT id FROM resource_actions WHERE task_id=? AND state='unknown'",
                (task["id"],),
            )
        )
        if state == "succeeded":
            assert not await store.call(
                lambda db: row(db, "SELECT id FROM resources WHERE owner_task_id=?", (task["id"],))
            )
    finally:
        await runtime.close()


async def test_dead_receipt_owner_proves_only_input_stop_and_preserves_original_receipt(store):
    import sys

    from test_runtime import ConversationModel

    runtime = Runtime(store, ConversationModel())
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(30)"
    )
    try:
        runtime.browser._directories()
        operation_id = "c" * 32
        receipt = {
            "version": 1,
            "id": operation_id,
            "payloadHash": "a" * 64,
            "state": "running",
            "inputStopped": False,
            "outcomeKnown": False,
        }
        path = runtime.browser.receipts / (operation_id + ".json")
        path.touch(mode=0o600)
        path.write_text(encoded(receipt))
        lock = path.with_suffix(".lock")
        lock.touch(mode=0o600)
        lock.write_text(str(process.pid))
        assert await runtime.browser._stored_receipt(operation_id) == receipt
        process.terminate()
        await process.wait()
        proof = await runtime.browser._stored_receipt(operation_id)
        assert proof["state"] == "unknown" and proof["inputStopped"] is True
        assert proof["outcomeKnown"] is False
        assert proof["stopEvidence"] == {"kind": "driver_process_exited", "pid": process.pid}
        assert json.loads(path.read_text()) == receipt
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()
        await runtime.close()


@pytest.mark.parametrize("owner", [None, "", "not-a-pid", "0", "999999999999999", "symlink"])
async def test_missing_or_invalid_process_claim_never_proves_input_stop(store, owner):
    from test_runtime import ConversationModel

    runtime = Runtime(store, ConversationModel())
    try:
        runtime.browser._directories()
        operation_id = "c" * 32
        receipt = {
            "version": 1,
            "id": operation_id,
            "payloadHash": "a" * 64,
            "state": "running",
            "inputStopped": False,
            "outcomeKnown": False,
        }
        path = runtime.browser.receipts / (operation_id + ".json")
        path.touch(mode=0o600)
        path.write_text(encoded(receipt))
        lock = path.with_suffix(".lock")
        if owner == "symlink":
            lock.symlink_to(path)
        elif owner is not None:
            lock.touch(mode=0o600)
            lock.write_text(owner)
        assert await runtime.browser._stored_receipt(operation_id) == receipt
    finally:
        await runtime.close()


async def test_stopped_unreadable_source_is_not_reopened_and_alternate_source_remains_available(
    store,
):
    from test_runtime import ConversationModel, until
    from test_tool_rejection_progress import Calls

    def opening(url):
        return {
            "name": "bash",
            "arguments": encoded(
                {
                    "argv": [
                        "roami",
                        "agent",
                        "capability",
                        "call",
                        "browser_open",
                        "--input",
                        encoded({"url": url}),
                    ]
                }
            ),
        }

    first, alternate = "https://blocked.example/pricing", "https://alternate.example/pricing"
    model = Calls([opening(first), opening(first), opening(alternate)])
    fixture = BrowserFixture()
    fixture.stop_known = False

    async def runner(argv, **options):
        result = await fixture(argv, **options)
        verb, flags, args = fixture.arguments(argv)
        if verb == "goto" and args[0] == first:
            fixture.receipts[flags["--operation-id"]].update(
                state="unknown", inputStopped=True, outcomeKnown=False
            )
            result["stdout"] = encoded(fixture.receipts[flags["--operation-id"]])
        return result

    runtime = Runtime(
        store, ConversationModel(), worker_model=model, settings=Settings(browser={"enabled": True})
    )
    runtime.browser.runner = runner
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Compare sources",
            key="source-recovery",
            target={"kind": "new_session", "resourceOnly": True},
            record_intent=True,
        )
        await runtime.start()
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM task_attempts WHERE task_id=? AND finished_ms IS NOT NULL",
                (task["id"],),
            ),
        )
        assert model.results[1]["error"] == "BROWSER_SOURCE_UNAVAILABLE"
        assert "another relevant public URL" in model.results[1]["recovery"]
        assert fixture.writes == ["new", "goto", "new", "goto"]
        assert fixture.url == alternate
        records = await store.call(
            lambda db: rows(
                db,
                "SELECT state,result_json FROM resource_actions WHERE task_id=? AND state='unknown'",
                (task["id"],),
            )
        )
        assert len(records) == 1
        assert json.loads(records[0]["result_json"])["outcomeKnown"] is False
    finally:
        await runtime.close()
