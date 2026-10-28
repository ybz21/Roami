import asyncio
import threading

import pytest

from roami_agent.conversation.transcript import Conversations
from roami_agent.storage.database import event


async def test_only_committed_events_wake_their_conversation_streams(store):
    conversations = Conversations(store)
    first = await conversations.create("local")
    other = await conversations.create("local")
    await asyncio.sleep(0)
    signals = store.conversation_events
    with (
        signals.subscribe(first["id"]) as a,
        signals.subscribe(first["id"]) as b,
        signals.subscribe(other["id"]) as unrelated,
    ):
        inserted, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()

        def write(db):
            event(db, first["id"], "fixture.committed", {})
            loop.call_soon_threadsafe(inserted.set)
            assert release.wait(5)

        committing = asyncio.create_task(store.call(write, write=True))
        try:
            await asyncio.wait_for(inserted.wait(), 2)
            assert not a.is_set() and not b.is_set() and not unrelated.is_set()
        finally:
            release.set()
            await committing
        await asyncio.wait_for(a.wait(), 2)
        assert b.is_set() and not unrelated.is_set()
        a.clear()
        b.clear()

        def rollback(db):
            event(db, first["id"], "fixture.rolled_back", {})
            raise ValueError("rollback")

        with pytest.raises(ValueError, match="rollback"):
            await store.call(rollback, write=True)
        await store.call(
            lambda db: db.execute("UPDATE conversations SET title='renamed'"), write=True
        )
        await asyncio.sleep(0)
        assert not a.is_set() and not b.is_set() and not unrelated.is_set()
    assert signals.listeners == {}


async def test_cancelled_caller_still_publishes_its_committed_event(store):
    conversation = await Conversations(store).create("local")
    await asyncio.sleep(0)
    with store.conversation_events.subscribe(conversation["id"]) as changed:
        inserted, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()

        def write(db):
            event(db, conversation["id"], "fixture.committed", {})
            loop.call_soon_threadsafe(inserted.set)
            assert release.wait(5)

        caller = asyncio.create_task(store.call(write, write=True))
        try:
            await asyncio.wait_for(inserted.wait(), 2)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
        finally:
            release.set()
        await asyncio.wait_for(changed.wait(), 2)
        assert any(
            item["kind"] == "fixture.committed"
            for item in await Conversations(store).events("local", conversation["id"])
        )
