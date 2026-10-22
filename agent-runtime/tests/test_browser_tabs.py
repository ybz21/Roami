"""Tab budgets span tasks; only proven, idle, unclaimed background tabs are recycled."""

import asyncio
import json

import pytest
from test_browser_driver import BrowserFixture
from test_resource_leases import controller
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.executors.browser_driver import BrowserDriver
from roami_agent.protocol.browser import browser_config
from roami_agent.protocol.errors import DomainError, ToolPreflightError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row, rows

BROWSER = "browser-fixture"


class PoolChrome(BrowserFixture):
    def __init__(self):
        super().__init__()
        self.targets = {"user-tab"}
        self.foreground = set()
        self.closed = []
        self.counter = 0
        self.unknown = False
        self.block_close = False
        self.closing = asyncio.Event()
        self.allow_close = asyncio.Event()

    async def __call__(self, argv, **options):
        verb, flags, _args = self.arguments(argv)
        if verb == "capabilities":
            result = json.loads((await super().__call__(argv, **options))["stdout"])
            result["features"].append("background_tab_close")
        elif verb == "tabs":
            assert flags["--expected-browser"] == BROWSER
            result = [{"targetId": t} for t in sorted(self.targets)]
        elif verb in {"new", "close"}:
            assert flags["--expected-browser"] == BROWSER
            operation = flags["--operation-id"]
            result = {
                "version": 1,
                "id": operation,
                "payloadHash": "a" * 64,
                "state": "succeeded",
                "inputStopped": True,
                "outcomeKnown": True,
                "result": {"stdout": "ok"},
            }
            if verb == "new":
                self.counter += 1
                target = "agent-" + str(self.counter)
                self.targets.add(target)
                result["result"]["stdout"] = encoded({"targetId": target, "url": "about:blank"})
            else:
                assert flags["--no-start"] and flags["--no-focus"] and flags["--only-if-background"]
                target = flags["--target"]
                self.closing.set()
                if self.block_close:
                    await self.allow_close.wait()
                self.closed.append(target)
                if target in self.foreground:
                    result.update(state="failed", errorCode="CHROME_TARGET_IN_USE")
                elif self.unknown:
                    result.update(state="unknown", inputStopped=False, outcomeKnown=False)
                else:
                    self.targets.remove(target)
            self.writes.append(verb)
            self.receipts[operation] = result
        else:
            return await super().__call__(argv, **options)
        return {"exitCode": 0, "stdout": encoded(result), "stderr": ""}


async def fixture(store):
    runtime = Runtime(store, ConversationModel(), settings=Settings(browser={"enabled": True}))
    chrome = PoolChrome()
    runtime.browser.runner = chrome

    async def receipt(operation):
        return chrome.receipts[operation]

    runtime.browser.receipt_reader = receipt
    return runtime, chrome


async def add_tab(runtime, chrome, target, *, idle_ms=0):
    chrome.targets.add(target)
    rid = await runtime.browser.tabs.track("alice", BROWSER, target)
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE browser_tabs SET idle_since_ms=? WHERE resource_id=?", (now_ms() - idle_ms, rid)
        ),
        write=True,
    )
    return rid


def test_browser_pool_configuration_is_bounded_at_twenty():
    assert browser_config({"enabled": True})["max_tabs"] == 20
    assert browser_config({"max_tabs": 20})["idle_timeout_seconds"] == 600
    for value in [{"max_tabs": 21}, {"idle_timeout_seconds": True}, {"idle_timeout_seconds": 0}]:
        with pytest.raises(DomainError, match="INVALID_BROWSER_CONFIG"):
            browser_config(value)


async def test_twenty_tabs_across_tasks_then_pressure_recycles_only_released_tab(store):
    runtime, chrome = await fixture(store)
    first, second = await controller(store), await controller(store, key="second")

    async def scope(binding, **options):
        return {"owner": "alice", "taskId": binding["taskId"], "runId": binding["runId"]}

    runtime.resources.scope = scope
    try:

        async def open_slot(index):
            task, run = first if index < 10 else second
            binding = {
                "owner": "alice",
                "taskId": task,
                "runId": run,
                "turnId": "turn",
                "toolCallId": "tab-" + str(index),
            }
            return await runtime.browser.open({}, binding)

        opened = await asyncio.gather(*(open_slot(index) for index in range(20)))
        assert len(chrome.targets) == 21 and "user-tab" in chrome.targets
        binding = {
            "owner": "alice",
            "taskId": first[0],
            "runId": first[1],
            "turnId": "turn",
            "toolCallId": "extra",
            "conversation": await store.call(
                lambda db: row(
                    db, "SELECT origin_conversation_id FROM tasks WHERE id=?", (first[0],)
                )["origin_conversation_id"]
            ),
        }
        await store.call(
            lambda db: db.execute(
                "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms) "
                "SELECT 'turn',conversation_id,id,'user','completed',0 FROM branches WHERE conversation_id=? LIMIT 1",
                (binding["conversation"],),
            ),
            write=True,
        )
        with pytest.raises(DomainError, match="BROWSER_TAB_BUDGET_EXCEEDED"):
            await runtime.browser.open({}, binding)
        restarted = BrowserDriver(
            store, runtime.settings, runtime.resources, runtime.artifacts, runner=chrome
        )
        with pytest.raises(ToolPreflightError, match="BROWSER_TAB_BUDGET_EXCEEDED"):
            await restarted.open(
                {"url": "https://another.example"}, dict(binding, toolCallId="retry")
            )
        assert chrome.counter == 20 and not chrome.closed
        lease = await store.call(
            lambda db: row(
                db, "SELECT * FROM resources WHERE id=?", (opened[0]["observation"]["resourceId"],)
            )
        )
        await runtime.resources.release("alice", lease["id"], *first, lease["lease_epoch"])
        await runtime.browser.open({}, binding)
        assert chrome.closed == ["agent-1"] and chrome.counter == 21
        assert "user-tab" in chrome.targets and len(chrome.targets) == 21
        assert (
            await store.call(
                lambda db: row(db, "SELECT count(*) AS n FROM browser_tabs WHERE state!='closed'")[
                    "n"
                ]
            )
            == 20
        )
    finally:
        await runtime.close()


async def test_idle_timeout_lru_and_foreground_takeover_and_unknown_protection(store):
    runtime, chrome = await fixture(store)
    try:
        young = await add_tab(runtime, chrome, "young", idle_ms=10_000)
        oldest = await add_tab(runtime, chrome, "oldest", idle_ms=900_000)
        foreground = await add_tab(runtime, chrome, "foreground", idle_ms=850_000)
        chrome.foreground.add("foreground")
        paused = await add_tab(runtime, chrome, "paused", idle_ms=800_000)
        await runtime.resources.pause("alice", paused)
        unknown = await add_tab(runtime, chrome, "unknown", idle_ms=750_000)
        task, run = await controller(store)
        lease = await runtime.resources.claim(
            "alice", task, run, "browser", f"browser:{BROWSER}:target:unknown", created=True
        )
        observed = await runtime.resources.observe(
            "alice", lease["id"], task, run, lease["lease_epoch"], "a" * 64, {}
        )
        action = await runtime.resources.begin(
            "alice",
            lease["id"],
            task,
            run,
            lease["lease_epoch"],
            observed["id"],
            observed["sceneEpoch"],
            {"verb": "goto"},
            "unknown",
        )
        await runtime.resources.finish(
            "alice", action["id"], "unknown", {"inputStopped": True, "outcomeKnown": False}
        )
        await runtime.resources.release_task("alice", task, run)
        await runtime.browser.tabs.sweep()
        assert chrome.closed == ["oldest", "foreground"]
        assert chrome.targets == {"user-tab", "young", "foreground", "paused", "unknown"}
        records = await store.call(lambda db: rows(db, "SELECT * FROM browser_tabs"))
        states = {r["resource_id"]: r["state"] for r in records}
        assert (
            states[oldest] == "closed"
            and states[young] == states[foreground] == states[paused] == states[unknown] == "open"
        )
        runtime.browser.tabs.next_sweep = 0
        await runtime.browser.tabs.sweep()
        assert chrome.closed == ["oldest", "foreground"]
    finally:
        await runtime.close()


async def test_unknown_close_survives_restart_without_replay_or_reclaim(store):
    runtime, chrome = await fixture(store)
    try:
        rid = await add_tab(runtime, chrome, "uncertain", idle_ms=900_000)
        chrome.unknown = True
        assert not await runtime.browser.tabs.recycle(rid, BROWSER)
        task, run = await controller(store)
        with pytest.raises(DomainError, match="RESOURCE_BUSY"):
            await runtime.resources.claim(
                "alice", task, run, "browser", f"browser:{BROWSER}:target:uncertain"
            )
        with pytest.raises(DomainError, match="RESOURCE_BUSY"):
            await runtime.resources.pause("alice", rid)
        restarted = BrowserDriver(
            store,
            runtime.settings,
            runtime.resources,
            runtime.artifacts,
            runner=chrome,
            receipt_reader=runtime.browser.receipt_reader,
        )
        await restarted.tabs.sync(BROWSER, chrome.targets)
        assert chrome.closed == ["uncertain"]
        assert (
            await store.call(
                lambda db: row(db, "SELECT state FROM browser_tabs WHERE resource_id=?", (rid,))[
                    "state"
                ]
            )
            == "closing"
        )
        chrome.targets.remove("uncertain")
        await restarted.tabs.sync(BROWSER, chrome.targets)
        assert (
            await store.call(
                lambda db: row(db, "SELECT state FROM browser_tabs WHERE resource_id=?", (rid,))[
                    "state"
                ]
            )
            == "closed"
        )
        assert chrome.closed == ["uncertain"]
    finally:
        await runtime.close()


async def test_cleanup_reservation_wins_only_once_and_blocks_new_takeover(store):
    runtime, chrome = await fixture(store)
    try:
        rid = await add_tab(runtime, chrome, "racing", idle_ms=900_000)
        chrome.block_close = True
        closing = asyncio.create_task(runtime.browser.tabs.recycle(rid, BROWSER))
        await chrome.closing.wait()
        assert not await runtime.browser.tabs.recycle(rid, BROWSER)
        with pytest.raises(DomainError, match="RESOURCE_BUSY"):
            await runtime.resources.pause("alice", rid)
        chrome.allow_close.set()
        assert await closing
        assert chrome.closed == ["racing"]
    finally:
        await runtime.close()


async def test_pre_upgrade_create_receipts_recover_only_proven_live_targets(store):
    runtime, chrome = await fixture(store)
    task, run = await controller(store)

    async def scope(binding, **options):
        return {"owner": "alice", "taskId": task, "runId": run}

    runtime.resources.scope = scope
    try:
        for number in range(3):
            await runtime.browser.open(
                {},
                {
                    "owner": "alice",
                    "taskId": task,
                    "runId": run,
                    "turnId": "turn",
                    "toolCallId": str(number),
                },
            )
        await runtime.resources.release_task("alice", task, run)
        await store.call(lambda db: db.execute("DELETE FROM browser_tabs"), write=True)
        await runtime.browser.tabs.sync(BROWSER, chrome.targets)
        recovered = await store.call(
            lambda db: rows(
                db, "SELECT target_id,idle_since_ms FROM browser_tabs ORDER BY target_id"
            )
        )
        assert [r["target_id"] for r in recovered] == ["agent-1", "agent-2", "agent-3"]
        assert all(r["idle_since_ms"] is not None for r in recovered)
        chrome.targets.remove("agent-2")
        await runtime.browser.tabs.sync(BROWSER, chrome.targets)
        assert (
            await store.call(
                lambda db: row(db, "SELECT state FROM browser_tabs WHERE target_id='agent-2'")[
                    "state"
                ]
            )
            == "closed"
        )
        assert not chrome.closed and "user-tab" in chrome.targets
    finally:
        await runtime.close()


async def test_catalog_enrolls_legacy_and_human_tabs_with_distinct_sleep_and_close_policies(store):
    runtime, chrome = await fixture(store)
    chrome.targets.update({"legacy-agent", "human-page"})
    old = now_ms() - 300_000
    metadata = {
        target: {
            "origin": "human" if target == "human-page" else "agent",
            "lastUsedAt": old,
            "sleepAfterSeconds": 60,
            "closeAfterSeconds": 0 if target == "human-page" else 600,
        }
        for target in chrome.targets
    }
    base = chrome.__call__
    slept = []

    async def runner(argv, **options):
        verb, flags, _ = chrome.arguments(argv)
        if verb == "tabs":
            result = [{"targetId": target, **metadata[target]} for target in chrome.targets]
        elif verb == "capabilities":
            result = json.loads((await base(argv, **options))["stdout"])
            result["features"].append("background_tab_sleep")
        elif verb == "sleep":
            target = flags["--target"]
            assert flags["--expected-origin"] == metadata[target]["origin"]
            assert int(flags["--expected-last-used"]) == old
            slept.append(target)
            metadata[target]["sleeping"] = True
            result = {
                "version": 1,
                "id": flags["--operation-id"],
                "payloadHash": "a" * 64,
                "state": "succeeded",
                "inputStopped": True,
                "outcomeKnown": True,
                "result": {"stdout": "ok"},
            }
            chrome.receipts[result["id"]] = result
        else:
            return await base(argv, **options)
        return {"exitCode": 0, "stdout": encoded(result), "stderr": ""}

    runtime.browser.runner = runner
    try:
        await runtime.browser.tabs.sync(BROWSER, await runtime.browser.tabs.inventory(BROWSER))
        records = await store.call(lambda db: rows(db, "SELECT * FROM browser_tabs"))
        assert len(records) == 3
        assert next(tab for tab in records if tab["target_id"] == "human-page")["origin"] == "human"
        assert all(tab["idle_since_ms"] > old for tab in records)
        # Simulate elapsed idle time after the first registration grace period.
        await store.call(
            lambda db: db.execute(
                "UPDATE browser_tabs SET idle_since_ms=?,last_used_ms=?", (old, old)
            ),
            write=True,
        )
        metadata["user-tab"]["pinned"] = True
        await runtime.browser.tabs.sweep()
        assert set(slept) == {"legacy-agent", "human-page"}
        assert not chrome.closed
        assert not await store.call(
            lambda db: row(db, "SELECT resource_id FROM browser_tabs WHERE state='closed'")
        )
        expired = now_ms() - 900_000
        for meta in metadata.values():
            meta["lastUsedAt"] = expired
        await store.call(
            lambda db: db.execute(
                "UPDATE browser_tabs SET idle_since_ms=?,last_used_ms=?,retry_after_ms=0",
                (expired, expired),
            ),
            write=True,
        )
        runtime.browser.tabs.next_sweep = 0
        await runtime.browser.tabs.sweep()
        assert chrome.closed == ["legacy-agent"]
        assert "human-page" in chrome.targets and "user-tab" in chrome.targets
    finally:
        await runtime.close()
