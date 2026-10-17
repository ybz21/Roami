"""Real X11 input stays on an isolated desktop and uses the observed pixel transform."""

import asyncio
import json
import os
import select
import shutil
import subprocess
import sys
import threading

import pytest

Xlib = pytest.importorskip("Xlib")
from Xlib import XK, X, display

from roami_agent.app import Runtime
from roami_agent.executors.x11_desktop import X11Desktop
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row, rows


class DesktopFixture:
    def __init__(self, name):
        self.name, self.value, self.saved = name, "", False
        self.clicks, self.keys = [], []
        self.connection = display.Display(name)
        screen = self.connection.screen()
        self.window = screen.root.create_window(
            50,
            50,
            350,
            200,
            0,
            screen.root_depth,
            X.InputOutput,
            X.CopyFromParent,
            background_pixel=screen.white_pixel,
            event_mask=X.ExposureMask | X.KeyPressMask | X.ButtonPressMask,
        )
        self.window.set_wm_name("Roami isolated desktop fixture")
        self.window.map()
        self.window.set_input_focus(X.RevertToParent, X.CurrentTime)
        self.font = self.connection.open_font("fixed")
        self.pen = self.window.create_gc(
            foreground=screen.black_pixel, background=screen.white_pixel, font=self.font
        )
        self.background = self.window.create_gc(foreground=screen.white_pixel)
        self.paint()

    def paint(self):
        self.window.fill_rectangle(self.background, 0, 0, 350, 200)
        for x, y, text in [
            (20, 25, "Desktop form"),
            (20, 45, "Name"),
            (25, 75, self.value),
            (35, 132, "Save"),
            (20, 175, "Saved" if self.saved else "Not saved"),
        ]:
            if text:
                self.window.image_text(self.pen, x, y, text)
        self.window.rectangle(self.pen, 20, 55, 200, 30)
        self.window.rectangle(self.pen, 20, 110, 120, 32)
        self.connection.sync()

    async def events(self):
        while True:
            changed = False
            while self.connection.pending_events():
                event = self.connection.next_event()
                if event.type == X.KeyPress:
                    symbol = self.connection.keycode_to_keysym(
                        event.detail, 1 if event.state & X.ShiftMask else 0
                    )
                    value = XK.keysym_to_string(symbol)
                    self.keys.append((event.detail, event.state))
                    if (
                        value
                        and len(value) == 1
                        and 32 <= ord(value) <= 126
                        and not event.state & X.ControlMask
                    ):
                        self.value += value
                        changed = True
                if event.type == X.ButtonPress:
                    self.clicks.append((event.event_x, event.event_y))
                    if 20 <= event.event_x <= 140 and 110 <= event.event_y <= 142:
                        self.saved = self.value == "Roami"
                        changed = True
            if changed:
                self.paint()
            await asyncio.sleep(0.002)

    def close(self):
        self.connection.close()


@pytest.fixture
async def desktop():
    if sys.platform != "linux" or not shutil.which("Xvfb"):
        pytest.skip("isolated Xvfb required")
    reader, writer = os.pipe()
    server = await asyncio.to_thread(
        subprocess.Popen,
        [
            "Xvfb",
            "-displayfd",
            str(writer),
            "-screen",
            "0",
            "800x600x24",
            "-nolisten",
            "tcp",
            "-ac",
        ],
        pass_fds=(writer,),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.close(writer)
    fixture = pump = None
    try:
        assert (await asyncio.to_thread(select.select, [reader], [], [], 5))[0]
        name = ":" + os.read(reader, 64).decode().strip()
        fixture = DesktopFixture(name)
        pump = asyncio.create_task(fixture.events())
        await asyncio.sleep(0.02)
        yield fixture
    finally:
        if pump:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
        if fixture:
            fixture.close()
        os.close(reader)
        server.terminate()
        await asyncio.to_thread(server.wait, 5)


class DesktopModel:
    model = "desktop-fixture-model"

    def __init__(self):
        self.step = 0

    async def stream(self, messages, tools):
        if "computer_open" not in {tool["function"]["name"] for tool in tools}:
            yield ModelEvent("text", '{"memories":[]}')
            return
        self.step += 1
        if self.step == 1:
            name, args = "computer_open", {}
        else:
            assert isinstance(messages[-1]["content"], list)
            assert messages[-1]["content"][1]["image_url"]["url"].startswith(
                "data:image/png;base64,"
            )
            result = json.loads(messages[-2]["content"])
            observation = result["observation"]
            if self.step == 2:
                name, args = (
                    "computer_act",
                    {"observationId": observation["id"], "kind": "type", "text": "Roami"},
                )
            elif self.step in {3, 5}:
                await asyncio.sleep(0.03)
                name, args = (
                    "computer_observe",
                    {"resourceId": observation["resourceId"], "focusOnly": True},
                )
            elif self.step == 4:
                transform = observation["screenshot"]
                assert transform["originX"] == 50 and transform["originY"] == 50
                name, args = (
                    "computer_act",
                    {
                        "observationId": observation["id"],
                        "kind": "click",
                        "x": (100 - transform["originX"]) / transform["scaleX"],
                        "y": (175 - transform["originY"]) / transform["scaleY"],
                    },
                )
            else:
                yield ModelEvent(
                    "text",
                    "Saved Roami in the isolated desktop form; screenshot evidence is attached.",
                )
                return
        yield ModelEvent(
            "tool",
            {
                "id": "desktop-" + str(self.step),
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            },
        )


async def test_native_worker_computer_use_drives_real_x11_and_verifies_actual_form(store, desktop):
    from test_runtime import until

    model = DesktopModel()

    async def verify(task, result):
        async with asyncio.timeout(2):
            while not desktop.saved:
                await asyncio.sleep(0.01)
        return desktop.saved and desktop.value == "Roami"

    runtime = Runtime(
        store,
        model,
        worker_model=model,
        settings=Settings(
            computer={"enabled": True, "display": desktop.name, "image_side": 400},
            model_capabilities={"images": True},
        ),
        verifier=verify,
    )
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Fill Roami and save the isolated desktop form",
            key="real-x11",
            record_intent=True,
        )
        runtime.wakeup.set()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM tasks WHERE id=? AND state='succeeded'", (task["id"],)
            ),
            timeout=10,
        )
        assert desktop.saved and desktop.value == "Roami" and len(desktop.clicks) == 1
        assert desktop.clicks[0] == (50, 125)
        actions = await store.call(
            lambda db: rows(db, "SELECT * FROM resource_actions WHERE task_id=?", (task["id"],))
        )
        assert len(actions) == 2 and all(action["state"] == "succeeded" for action in actions)
        assert not await store.call(
            lambda db: row(db, "SELECT id FROM resources WHERE owner_task_id=?", (task["id"],))
        )
        assert len(await runtime.artifacts.list("alice", task_id=task["id"])) == 5
        for action in actions:
            assert (await runtime.desktop._io(runtime.desktop._read_receipt, action))[
                "inputStopped"
            ]
    finally:
        await runtime.close()


async def test_x11_scene_change_blocks_input_and_ascii_case_and_named_combos_are_exact(desktop):
    adapter = X11Desktop(desktop.name)
    try:
        scene, _ = adapter.observe()
        desktop.window.configure(x=70)
        desktop.connection.sync()
        with pytest.raises(DomainError, match="DESKTOP_SCENE_CHANGED"):
            adapter.act(
                {"kind": "type", "text": "must not type"}, scene["signature"], threading.Event()
            )
        assert desktop.value == ""
        desktop.window.configure(x=50)
        desktop.connection.sync()
        scene, _ = adapter.observe()
        assert (
            adapter.act({"kind": "type", "text": "Roami"}, scene["signature"], threading.Event())[
                "state"
            ]
            == "succeeded"
        )
        await asyncio.sleep(0.03)
        assert desktop.value == "Roami"
        scene, _ = adapter.observe()
        assert (
            adapter.act({"kind": "key", "key": "Ctrl+L"}, scene["signature"], threading.Event())[
                "state"
            ]
            == "succeeded"
        )
        await asyncio.sleep(0.02)
        control_events = [state for _, state in desktop.keys if state & X.ControlMask]
        assert control_events and all(not state & X.ShiftMask for state in control_events)
        assert desktop.value == "Roami"
    finally:
        adapter.close()


class DelayedDesktop:
    driver_id = "delayed-fixture"
    failure_types = (OSError,)

    def __init__(self, known):
        self.known = known
        self.started, self.release = threading.Event(), threading.Event()
        self.writes = 0

    def observe(self, *, focus_only=False):
        from test_browser_driver import PNG

        return {
            "driverId": self.driver_id,
            "signature": "a" * 64,
            "coordinateSpace": "image_pixels",
            "screenshot": {
                "width": 1,
                "height": 1,
                "scaleX": 1,
                "scaleY": 1,
                "originX": 0,
                "originY": 0,
            },
        }, PNG

    def act(self, action, signature, cancelled):
        self.started.set()
        while not self.release.wait(0.005):
            if self.known and cancelled.is_set():
                return {"state": "cancelled", "inputStopped": True, "outcomeKnown": True}
        self.writes += 1
        return {"state": "succeeded", "inputStopped": True, "outcomeKnown": True, "inputSent": True}

    def close(self):
        pass


class DelayedDesktopModel:
    model = "delayed-desktop-model"

    async def stream(self, messages, tools):
        if "computer_open" not in {tool["function"]["name"] for tool in tools}:
            yield ModelEvent("text", "Quick answer")
            return
        if messages[-1]["role"] != "user" or not isinstance(messages[-1]["content"], list):
            name, args = "computer_open", {}
        else:
            observed = json.loads(messages[-2]["content"])["observation"]
            name, args = (
                "computer_act",
                {"observationId": observed["id"], "kind": "key", "key": "Return"},
            )
        yield ModelEvent(
            "tool",
            {
                "id": name,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            },
        )


@pytest.mark.parametrize("known,expected", [(True, "cancelled"), (False, "interrupted")])
async def test_desktop_cancel_only_releases_after_actual_stop_and_late_receipt_never_promotes_task(
    store, known, expected
):
    from test_runtime import until

    adapter = DelayedDesktop(known)
    runtime = Runtime(
        store,
        DelayedDesktopModel(),
        settings=Settings(
            computer={"enabled": True}, model_capabilities={"images": True}, workers=1
        ),
    )
    runtime.desktop.factory = lambda: adapter
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", conversation["id"], "Controlled input", key="delayed-input", record_intent=True
        )
        runtime.wakeup.set()
        assert await asyncio.to_thread(adapter.started.wait, 3)
        other = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit(
            "alice", other["id"], "quick-main", "Reply while desktop input is busy"
        )
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
            timeout=1,
        )
        await runtime.tasks.cancel("alice", task["id"])
        runtime.wakeup.set()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM tasks WHERE id=? AND state=?", (task["id"], expected)
            ),
            timeout=5,
        )
        held = await store.call(
            lambda db: rows(db, "SELECT * FROM resources WHERE owner_task_id=?", (task["id"],))
        )
        assert bool(held) is (not known)
        if held:
            assert all(item["state"] == "quarantined" for item in held)
        assert adapter.writes == 0
        adapter.release.set()
        await until(
            store,
            lambda db: not row(db, "SELECT id FROM resources WHERE owner_task_id=?", (task["id"],)),
            timeout=5,
        )
        assert (
            await store.call(
                lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))
            )
        )["state"] == expected
        assert adapter.writes == (0 if known else 1)
    finally:
        adapter.release.set()
        await runtime.close()


async def test_computer_is_disabled_by_default_and_missing_display_is_explicit(store, monkeypatch):
    runtime = Runtime(store, DesktopModel())
    try:
        assert not any(
            tool["function"]["name"].startswith("computer_")
            for tool in runtime.tools.catalog("worker")
        )
        monkeypatch.delenv("DISPLAY", raising=False)
        with pytest.raises(DomainError, match="DESKTOP_DRIVER_UNAVAILABLE"):
            runtime.desktop._connect()
    finally:
        await runtime.close()


async def test_model_deadline_with_unconfirmed_input_is_interrupted_not_retryable_failure(store):
    from test_runtime import until

    adapter = DelayedDesktop(False)
    runtime = Runtime(
        store,
        DelayedDesktopModel(),
        settings=Settings(
            computer={"enabled": True},
            model_capabilities={"images": True},
            timeout_seconds=1,
            workers=1,
        ),
    )
    runtime.desktop.factory = lambda: adapter
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Input with a short deadline",
            key="deadline-input",
            record_intent=True,
        )
        runtime.wakeup.set()
        assert await asyncio.to_thread(adapter.started.wait, 2)
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM tasks WHERE id=? AND state='interrupted'", (task["id"],)
            ),
            timeout=5,
        )
        attempt = await store.call(
            lambda db: row(
                db, "SELECT result_json FROM task_attempts WHERE task_id=?", (task["id"],)
            )
        )
        result = json.loads(attempt["result_json"])
        assert result["outcomeKnown"] is False and result["retryable"] is False
        assert await store.call(
            lambda db: row(
                db,
                "SELECT id FROM resources WHERE owner_task_id=? AND state='quarantined'",
                (task["id"],),
            )
        )
    finally:
        adapter.release.set()
        await runtime.close()
