"""Task-scoped desktop control with durable terminal receipts and explicit stop proof."""

import asyncio
import json
import math
import os
import re
import stat
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from roami_agent.executors.input_cancellation import (
    input_started,
    input_stopped,
    passive_cancel_boundary,
)
from roami_agent.protocol.computer import computer_config
from roami_agent.protocol.errors import DomainError, ToolCancellation
from roami_agent.protocol.identity import identity
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, row, rows


class DesktopDriver:
    def __init__(self, database, settings, resources, artifacts, *, factory=None):
        self.db, self.settings, self.resources, self.artifacts = (
            database,
            settings,
            resources,
            artifacts,
        )
        self.config = computer_config(settings.computer)
        self.root = database.data_root.resolve() / "agents/desktop-operations"
        self.factory, self.adapter = factory, None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-desktop")
        self.capacity = asyncio.Semaphore(4)
        self.pending, self.calls, self.closed = set(), set(), False
        self.closing = None
        self.reconcile_cursor = ""
        if self.config["enabled"] and settings.model_capabilities.get("images") is not True:
            raise DomainError("COMPUTER_VISION_REQUIRED", 503)

    async def _io(self, operation, *args):
        await self.capacity.acquire()
        if self.closed:
            self.capacity.release()
            raise DomainError("DESKTOP_DRIVER_CLOSED", 503)
        future = asyncio.get_running_loop().run_in_executor(self.pool, operation, *args)
        self.pending.add(future)

        def done(value):
            self.pending.discard(value)
            self.capacity.release()
            if not value.cancelled():
                value.exception()

        future.add_done_callback(done)
        return await asyncio.shield(future)

    def _connect(self):
        if self.adapter is not None:
            return self.adapter
        if self.factory:
            self.adapter = self.factory()
            return self.adapter
        name = self.config.get("display") or os.environ.get("DISPLAY", "")
        if sys.platform != "linux" or not re.fullmatch(r":[0-9]{1,5}(?:\.[0-9]{1,2})?", name):
            raise DomainError("DESKTOP_DRIVER_UNAVAILABLE", 503)
        try:
            from Xlib.error import DisplayConnectionError, DisplayNameError

            from roami_agent.executors.x11_desktop import X11Desktop
        except ImportError:
            raise DomainError("DESKTOP_DRIVER_UNAVAILABLE", 503) from None
        try:
            self.adapter = X11Desktop(name, image_side=self.config["image_side"])
        except (DisplayConnectionError, DisplayNameError, OSError):
            raise DomainError("DESKTOP_DRIVER_UNAVAILABLE", 503) from None
        return self.adapter

    def _directories(self):
        for directory in (self.root.parent, self.root):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise DomainError("DESKTOP_RECEIPT_UNAVAILABLE", 503)

    def _read_receipt(self, action):
        if not re.fullmatch(r"[a-f0-9]{32}", action["id"]):
            raise DomainError("DESKTOP_RECEIPT_UNAVAILABLE", 503)
        self._directories()
        try:
            descriptor = os.open(
                self.root / (action["id"] + ".json"), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            )
            with os.fdopen(descriptor, "rb") as file:
                info = os.fstat(file.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 64000 or info.st_mode & 0o077:
                    raise ValueError
                receipt = json.load(file)
            if not isinstance(receipt, dict):
                raise TypeError
            if (
                receipt.get("id") != action["id"]
                or receipt.get("payloadHash") != action["payload_sha256"]
                or type(receipt.get("version")) is not int
                or receipt["version"] != 1
                or receipt.get("state") not in {"succeeded", "failed", "cancelled", "unknown"}
                or not isinstance(receipt.get("inputStopped"), bool)
                or not isinstance(receipt.get("outcomeKnown"), bool)
                or (
                    receipt["state"] != "unknown"
                    and not (receipt["inputStopped"] and receipt["outcomeKnown"])
                )
                or (receipt["state"] == "unknown" and receipt["outcomeKnown"])
            ):
                raise ValueError
            return receipt
        except (OSError, ValueError, TypeError):
            raise DomainError("DESKTOP_RECEIPT_UNAVAILABLE", 503) from None

    def _save_receipt(self, action, result):
        receipt = {
            "version": 1,
            "id": action["id"],
            "payloadHash": action["payload_sha256"],
            **result,
        }
        temporary = self.root / (action["id"] + "." + identity() + ".tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as file:
                file.write(encoded(receipt).encode())
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.root / (action["id"] + ".json"))
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return receipt
        finally:
            temporary.unlink(missing_ok=True)

    def _execute(self, action, driver_id, body, signature, cancelled):
        self._directories()
        try:
            claim = os.open(
                self.root / (action["id"] + ".lock"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
        except FileExistsError:
            return self._read_receipt(action)
        try:
            os.write(claim, str(os.getpid()).encode())
            os.fsync(claim)
        finally:
            os.close(claim)
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        if cancelled.is_set():
            return self._save_receipt(
                action, {"state": "cancelled", "inputStopped": True, "outcomeKnown": True}
            )
        adapter = self._connect()
        if adapter.driver_id != driver_id:
            return self._save_receipt(
                action,
                {
                    "state": "failed",
                    "inputStopped": True,
                    "outcomeKnown": True,
                    "error": "DESKTOP_INSTANCE_CHANGED",
                },
            )
        try:
            result = adapter.act(body, signature, cancelled)
        except DomainError as exc:
            result = {
                "state": "failed",
                "inputStopped": True,
                "outcomeKnown": True,
                "error": exc.code,
            }
        except adapter.failure_types:
            result = {
                "state": "unknown",
                "inputStopped": False,
                "outcomeKnown": False,
                "error": "DESKTOP_ACTION_OUTCOME_UNKNOWN",
            }
        return self._save_receipt(action, result)

    async def _finish(self, scope, action, receipt):
        if receipt["inputStopped"]:
            input_stopped()
        state = (
            "succeeded"
            if receipt["state"] == "succeeded"
            else "unknown"
            if receipt["state"] == "unknown"
            else "failed"
        )
        result = {
            "operationId": action["id"],
            "driverState": receipt["state"],
            "inputStopped": receipt["inputStopped"],
            "outcomeKnown": receipt["outcomeKnown"],
            "error": receipt.get("error"),
            "inputSent": receipt.get("inputSent"),
        }
        await self.resources.finish(scope["owner"], action["id"], state, result)
        return state, result

    async def _claim(self, scope, driver_id, binding):
        while True:
            await self.resources.scope(binding, input_action=True)
            try:
                return await self.resources.claim(
                    scope["owner"],
                    scope["taskId"],
                    scope["runId"],
                    "desktop",
                    "desktop:x11:" + driver_id,
                )
            except DomainError as exc:
                if exc.code not in {"RESOURCE_BUSY", "RESOURCE_ACTION_PENDING"}:
                    raise
                await asyncio.sleep(0.2)

    @passive_cancel_boundary
    async def open(self, args, binding):
        if not self.settings.model_capabilities.get("images"):
            raise DomainError("COMPUTER_VISION_REQUIRED", 503)
        scope = await self.resources.scope(binding, input_action=True)
        driver_id = await self._io(lambda: self._connect().driver_id)
        resource = await self._claim(scope, driver_id, binding)
        return await self.observe({"resourceId": resource["id"]}, binding)

    def _capture(self, focus_only):
        adapter = self._connect()
        try:
            return adapter.observe(focus_only=focus_only)
        except adapter.failure_types:
            raise DomainError("DESKTOP_DRIVER_UNAVAILABLE", 503) from None

    @passive_cancel_boundary
    async def observe(self, args, binding):
        scope = await self.resources.scope(binding)
        resource = await self.resources.resource(scope, args["resourceId"])
        if resource["kind"] != "desktop" or not resource["resource_key"].startswith("desktop:x11:"):
            raise DomainError("DESKTOP_RESOURCE_SCOPE_INVALID", 409)
        driver_id = resource["resource_key"][12:]
        resource = await self._claim(scope, driver_id, binding)
        observed, image = await self._io(self._capture, args.get("focusOnly", False))
        if observed["driverId"] != driver_id:
            raise DomainError("DESKTOP_INSTANCE_CHANGED", 409)
        artifact = await self.artifacts.put(
            scope["owner"],
            image,
            mime_type="image/png",
            name="desktop-observation.png",
            task_id=scope["taskId"],
            message_id=binding.get("assistantMessageId"),
            metadata={"source": "computer", "resourceId": resource["id"], **observed["screenshot"]},
        )
        observed["screenshotRef"] = artifact["id"]
        result = await self.resources.observe(
            scope["owner"],
            resource["id"],
            scope["taskId"],
            scope["runId"],
            resource["lease_epoch"],
            observed["signature"],
            observed,
        )
        return {"observation": result, "artifactRefs": [artifact]}

    @passive_cancel_boundary
    async def act(self, args, binding):
        scope = await self.resources.scope(binding, input_action=True)
        observed = await self.resources.observation(scope, args["observationId"])
        resource = await self.resources.resource(scope, observed["resource_id"])
        if resource["kind"] != "desktop":
            raise DomainError("DESKTOP_RESOURCE_SCOPE_INVALID", 409)
        body = json.loads(observed["body_json"])
        manifest = await self.db.call(
            lambda db: row(
                db,
                "SELECT parts_json FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no DESC LIMIT 1",
                (binding["turnId"],),
            )
        )
        if not manifest or not any(
            image.get("observationId") == observed["id"]
            and image.get("artifactId") == body["screenshotRef"]
            for image in json.loads(manifest["parts_json"]).get("imageEvidence", [])
        ):
            raise DomainError("COMPUTER_IMAGE_REQUIRED", 409)
        action_body = {key: value for key, value in args.items() if key != "observationId"}
        action_body["focusOnly"] = body.get("captureMode") == "focus"
        if args["kind"] == "click":
            action_body["button"] = {"left": 1, "middle": 2, "right": 3}[args.get("button", "left")]
        if args["kind"] in {"click", "scroll"}:
            for key, dimension in (("x", "width"), ("y", "height")):
                if (
                    type(args[key]) not in (int, float)
                    or not math.isfinite(args[key])
                    or not 0 <= args[key] < body["screenshot"][dimension]
                ):
                    raise DomainError("DESKTOP_COORDINATES_INVALID", 409)
            action_body["transform"] = body["screenshot"]
        action = await self.resources.begin(
            scope["owner"],
            resource["id"],
            scope["taskId"],
            scope["runId"],
            observed["lease_epoch"],
            observed["id"],
            observed["scene_epoch"],
            action_body,
            binding["turnId"] + ":" + binding["toolCallId"] + ":desktop",
        )
        if not action["dispatch"]:
            if action["state"] != "succeeded":
                raise DomainError("TOOL_OUTCOME_UNKNOWN")
            return json.loads(action["result_json"])
        cancelled = threading.Event()
        input_started()
        running = asyncio.create_task(
            self._io(
                self._execute, action, body["driverId"], action_body, body["signature"], cancelled
            )
        )
        self.calls.add(running)

        def completed(call):
            self.calls.discard(call)
            if not call.cancelled():
                call.exception()

        running.add_done_callback(completed)
        receipt = None
        try:
            receipt = await asyncio.shield(running)
        except asyncio.CancelledError:
            cancelled.set()
            await asyncio.wait({running}, timeout=2)
            if running.done() and not running.cancelled() and running.exception() is None:
                receipt = running.result()
            if receipt:
                await self._finish(scope, action, receipt)
            else:
                await self.resources.finish(
                    scope["owner"],
                    action["id"],
                    "unknown",
                    {"inputStopped": False, "outcomeKnown": False},
                )
            raise ToolCancellation(
                input_stopped=bool(receipt and receipt["inputStopped"])
            ) from None
        except (OSError, DomainError):
            await self.resources.finish(
                scope["owner"],
                action["id"],
                "unknown",
                {"inputStopped": False, "outcomeKnown": False},
            )
            raise DomainError("TOOL_OUTCOME_UNKNOWN") from None
        state, result = await self._finish(scope, action, receipt)
        if state == "unknown":
            raise DomainError("TOOL_OUTCOME_UNKNOWN")
        if state != "succeeded":
            raise DomainError(receipt.get("error") or "DESKTOP_ACTION_CANCELLED", 409)
        try:
            return {
                **await self.observe(
                    {"resourceId": resource["id"], "focusOnly": action_body["focusOnly"]}, binding
                ),
                "action": result,
                "needsVerification": True,
            }
        except (OSError, DomainError):
            return {
                "resourceId": resource["id"],
                "action": result,
                "needsVerification": True,
                "error": "DESKTOP_OBSERVATION_UNAVAILABLE",
            }

    async def reconcile(self):
        pending = await self.db.call(
            lambda db: rows(
                db,
                "SELECT a.*,r.owner_id,t.origin_conversation_id FROM resource_actions a "
                "JOIN resources r ON r.id=a.resource_id JOIN tasks t ON t.id=a.task_id "
                "WHERE r.kind='desktop' AND a.state='unknown' "
                "AND COALESCE(json_extract(a.result_json,'$.inputStopped'),0)!=1 "
                "AND a.id>? ORDER BY a.id LIMIT 16",
                (self.reconcile_cursor,),
            )
        )
        self.reconcile_cursor = pending[-1]["id"] if pending else ""
        for action in pending:
            try:
                receipt = await self._io(self._read_receipt, action)
                if not receipt["inputStopped"]:
                    continue
                await self._finish({"owner": action["owner_id"]}, action, receipt)

                def record(db, action=action, receipt=receipt):
                    if not row(
                        db,
                        "SELECT id FROM events WHERE event_key=?",
                        ("desktop-reconciled:" + action["id"],),
                    ):
                        event(
                            db,
                            action["origin_conversation_id"],
                            "task.resource_reconciled",
                            {
                                "taskId": action["task_id"],
                                "runId": action["run_id"],
                                "actionId": action["id"],
                                "inputStopped": True,
                                "outcomeKnown": receipt["outcomeKnown"],
                            },
                            task_id=action["task_id"],
                            key="desktop-reconciled:" + action["id"],
                        )
                    return not row(
                        db,
                        "SELECT id FROM task_attempts WHERE id=? AND state IN ('starting','running')",
                        (action["run_id"],),
                    )

                if await self.db.call(record, write=True):
                    await self.resources.release_task(
                        action["owner_id"], action["task_id"], action["run_id"]
                    )
            except (DomainError, OSError):
                continue

    async def close(self):
        if not self.closing:
            self.closing = asyncio.create_task(self._close())
        await asyncio.shield(self.closing)

    async def _close(self):
        self.closed = True
        await asyncio.gather(
            *(asyncio.shield(future) for future in tuple(self.pending)), return_exceptions=True
        )
        await asyncio.gather(*tuple(self.calls), return_exceptions=True)
        if self.adapter:
            await asyncio.get_running_loop().run_in_executor(self.pool, self.adapter.close)
        self.pool.shutdown(wait=True)
