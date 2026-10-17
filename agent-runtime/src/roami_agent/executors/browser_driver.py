"""Browser Use over the unified CLI with durable, task-scoped control receipts."""

import asyncio
import hashlib
import json
import math
import os
import re
import stat
import struct
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from roami_agent.executors.input_cancellation import (
    input_started,
    input_stopped,
    passive_cancel_boundary,
)
from roami_agent.protocol.browser import browser_config
from roami_agent.protocol.errors import DomainError, ToolCancellation
from roami_agent.protocol.identity import identity
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, rows
from roami_agent.tools.process import execute


class BrowserDriver:
    def __init__(
        self, database, settings, resources, artifacts, *, runner=execute, receipt_reader=None
    ):
        self.db, self.settings, self.resources, self.artifacts = (
            database,
            settings,
            resources,
            artifacts,
        )
        self.config, self.runner = browser_config(settings.browser), runner
        self.root = database.data_root.resolve()
        self.receipts = self.root / "agents/browser-operations"
        self.captures = self.root / "agents/browser-captures"
        self.socket_root = Path(tempfile.gettempdir()) / ("roami-browser-" + str(os.getuid()))
        self.instance = hashlib.sha256(str(self.root).encode()).hexdigest()[:24]
        self.reconcile_cursor = ""
        self.receipt_reader = receipt_reader or self._stored_receipt

    def _read_receipt_file(self, operation_id):
        if not re.fullmatch(r"[a-f0-9]{32}", operation_id):
            raise DomainError("BROWSER_DRIVER_PROTOCOL_INVALID", 503)
        for directory in (self.root / "agents", self.receipts):
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise DomainError("BROWSER_PRIVATE_DIRECTORY_INVALID", 503)
        descriptor = os.open(
            self.receipts / (operation_id + ".json"), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        )
        with os.fdopen(descriptor, "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 256_000:
                raise DomainError("BROWSER_DRIVER_PROTOCOL_INVALID", 503)
            try:
                return json.load(file)
            except (ValueError, TypeError):
                raise DomainError("BROWSER_DRIVER_PROTOCOL_INVALID", 503) from None

    async def _stored_receipt(self, operation_id):
        return await asyncio.to_thread(self._read_receipt_file, operation_id)

    async def reconcile(self):
        pending = await self.db.call(
            lambda db: rows(
                db,
                "SELECT a.*,r.owner_id,t.origin_conversation_id FROM resource_actions a "
                "JOIN resources r ON r.id=a.resource_id JOIN tasks t ON t.id=a.task_id "
                "WHERE r.kind='browser' AND a.state='unknown' "
                "AND COALESCE(json_extract(a.result_json,'$.inputStopped'),0)!=1 "
                "AND a.id>? ORDER BY a.id LIMIT 16",
                (self.reconcile_cursor,),
            )
        )
        self.reconcile_cursor = pending[-1]["id"] if pending else ""
        for action in pending:
            try:
                receipt = self._receipt(await self.receipt_reader(action["id"]), action["id"])
                if not receipt["inputStopped"]:
                    continue
                await self._complete({"owner": action["owner_id"]}, action, receipt)

                def record(db, action=action, receipt=receipt):
                    recorded = db.execute(
                        "SELECT id FROM events WHERE event_key=?",
                        ("resource-reconciled:" + action["id"],),
                    ).fetchone()
                    if not recorded:
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
                            key="resource-reconciled:" + action["id"],
                        )
                    return not db.execute(
                        "SELECT id FROM task_attempts WHERE id=? AND state IN ('starting','running')",
                        (action["run_id"],),
                    ).fetchone()

                if await self.db.call(record, write=True):
                    await self.resources.release_task(
                        action["owner_id"], action["task_id"], action["run_id"]
                    )
            except (DomainError, OSError, TimeoutError):
                continue

    def _directories(self):
        for path in [self.socket_root, self.root / "agents", self.receipts, self.captures]:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise DomainError("BROWSER_PRIVATE_DIRECTORY_INVALID", 503)

    async def _cli(self, verb, *args, operation_id=None, browser_id=None, signature=None):
        await asyncio.to_thread(self._directories)
        argv = [
            self.settings.cli_bin,
            "chrome",
            verb,
            *map(str, args),
            "--no-retry",
            "--no-focus",
            "--timeout",
            "5000",
        ]
        if self.config.get("endpoint"):
            argv += ["--cdp", self.config["endpoint"]]
        if operation_id:
            argv += ["--operation-id", operation_id, "--receipt-root", str(self.receipts)]
        if browser_id:
            argv += ["--expected-browser", browser_id]
        if signature:
            argv += ["--expected-scene", signature]
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in self.settings.provider_key_environments()
        }
        env.update(
            ROAMI_DATA=str(self.root),
            ROAMI_HOME=os.environ.get("ROAMI_HOME", str(self.root)),
            TTMUX_CHROME_SOCK=str(self.socket_root / (self.instance + ".sock")),
            TTMUX_CHROME_DAEMON_LOG=str(self.socket_root / (self.instance + ".log")),
        )
        answer = await self.runner(argv, env=env, timeout=20, max_bytes=512_000)
        if answer["exitCode"]:
            match = re.search(r"\b(CHROME_[A-Z_]{1,80})\b", answer.get("stderr", ""))
            raise DomainError(match[1] if match else "BROWSER_DRIVER_UNAVAILABLE", 503)
        try:
            return json.loads(answer["stdout"])
        except (ValueError, TypeError) as exc:
            raise DomainError("BROWSER_DRIVER_PROTOCOL_INVALID", 503) from exc

    async def _claim(self, scope, resource_key, *, created=False, binding=None):
        started = time.monotonic()
        while True:
            try:
                if binding:
                    await self.resources.scope(binding, input_action=True)
                return await self.resources.claim(
                    scope["owner"],
                    scope["taskId"],
                    scope["runId"],
                    "browser",
                    resource_key,
                    created=created,
                )
            except DomainError as exc:
                if exc.code not in {"RESOURCE_BUSY", "RESOURCE_ACTION_PENDING"}:
                    raise
                if binding and binding.get("progress"):
                    await binding["progress"](time.monotonic() - started)
                await asyncio.sleep(0.2)

    @staticmethod
    def _read_capture(path, max_bytes):
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or not 24 <= info.st_size <= max_bytes:
                raise DomainError("BROWSER_SCREENSHOT_INVALID", 503)
            body = file.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise DomainError("BROWSER_SCREENSHOT_INVALID", 503)
            return body

    @staticmethod
    def _observation(body, path):
        if not isinstance(body, dict):
            raise DomainError("BROWSER_DRIVER_PROTOCOL_INVALID", 503)
        screenshot = body.get("screenshot")
        viewport = body.get("viewportSize")
        if (
            not isinstance(body.get("signature"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", body["signature"])
            or not all(isinstance(body.get(key), str) for key in ("url", "title", "domText"))
            or not isinstance(body.get("controls"), list)
            or len(body["controls"]) > 64
            or not all(isinstance(item, dict) for item in body["controls"])
            or not isinstance(viewport, dict)
        ):
            raise DomainError("BROWSER_DRIVER_PROTOCOL_INVALID", 503)
        if any(
            type(viewport.get(key)) is not int or not 1 <= viewport[key] <= 32768
            for key in ("width", "height")
        ):
            raise DomainError("BROWSER_SCREENSHOT_INVALID", 503)
        if len(encoded(body).encode()) > 64_000:
            raise DomainError("BROWSER_OBSERVATION_LIMIT", 503)
        if path is None:
            if screenshot is not None:
                raise DomainError("BROWSER_DRIVER_PROTOCOL_INVALID", 503)
            return dict(body), None
        if not isinstance(screenshot, dict) or screenshot.get("path") != str(path):
            raise DomainError("BROWSER_DRIVER_PROTOCOL_INVALID", 503)
        for key in ("width", "height"):
            if type(screenshot.get(key)) is not int or not 1 <= screenshot[key] <= 32768:
                raise DomainError("BROWSER_SCREENSHOT_INVALID", 503)
        for key, dimension in (("scaleX", "width"), ("scaleY", "height")):
            value = screenshot.get(key)
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not math.isclose(value, screenshot[dimension] / viewport[dimension])
            ):
                raise DomainError("BROWSER_SCREENSHOT_INVALID", 503)
        return dict(body), {key: screenshot[key] for key in ("width", "height", "scaleX", "scaleY")}

    @staticmethod
    def _view(observation):
        view = dict(observation)
        view["domText"] = view.get("domText", "").encode()[:3000].decode(errors="ignore")
        view["url"] = view.get("url", "").encode()[:1200].decode(errors="ignore")
        controls = view.get("controls", [])
        view["controls"] = controls[:12]
        view["controlsTruncated"] = view.get("controlsTruncated", False) or len(controls) > 12
        while len(encoded(view).encode()) > 8000 and view["controls"]:
            view["controls"].pop()
            view["controlsTruncated"] = True
        if len(encoded(view).encode()) > 8000:
            raise DomainError("BROWSER_OBSERVATION_LIMIT", 503)
        return view

    async def capabilities(self):
        result = await self._cli("capabilities")
        features = result.get("features") if isinstance(result, dict) else None
        if (
            not isinstance(features, list)
            or not all(isinstance(value, str) for value in features)
            or not {
                "target_id",
                "operation_receipts",
                "scene_observation",
                "expected_scene",
            }.issubset(features)
            or not isinstance(result.get("browserId"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", result["browserId"])
        ):
            raise DomainError("BROWSER_DRIVER_UNAVAILABLE", 503)
        return result

    @staticmethod
    def _target(resource):
        match = re.fullmatch(
            r"browser:([A-Za-z0-9_-]{1,128}):target:([A-Za-z0-9_-]{1,128})",
            resource["resource_key"],
        )
        if resource["kind"] != "browser" or not match:
            raise DomainError("BROWSER_RESOURCE_SCOPE_INVALID", 409)
        return match[1], match[2]

    @staticmethod
    def _receipt(value, operation_id):
        invalid = not isinstance(value, dict)
        if not invalid:
            state, stopped, known = (
                value.get("state"),
                value.get("inputStopped"),
                value.get("outcomeKnown"),
            )
            invalid = (
                value.get("id") != operation_id
                or type(value.get("version")) is not int
                or value["version"] != 1
                or state
                not in {"accepted", "running", "succeeded", "failed", "cancelled", "unknown"}
                or not isinstance(stopped, bool)
                or not isinstance(known, bool)
                or state in {"succeeded", "failed", "cancelled"}
                and (not stopped or not known)
                or state in {"accepted", "running"}
                and (stopped or known)
                or state == "unknown"
                and known
            )
            if value.get("receiptExists") is False:
                invalid = (
                    invalid
                    or value.get("cancelRequested") is not True
                    or state not in {"cancelled", "unknown"}
                )
            else:
                invalid = (
                    invalid
                    or not isinstance(value.get("payloadHash"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", value.get("payloadHash", ""))
                )
            output = value.get("result", {})
            invalid = (
                invalid
                or not isinstance(output, dict)
                or not isinstance(output.get("stdout", ""), str)
            )
            if not invalid:
                invalid = len(output.get("stdout", "").encode()) > 128_000
        if invalid:
            raise DomainError("BROWSER_DRIVER_PROTOCOL_INVALID", 503)
        return value

    @staticmethod
    def _result(receipt):
        return {
            "inputStopped": receipt["inputStopped"],
            "outcomeKnown": receipt["outcomeKnown"],
            "operationId": receipt["id"],
            "driverState": receipt["state"],
            "error": receipt.get("errorCode"),
            "output": receipt.get("result", {}).get("stdout", ""),
        }

    async def _complete(self, scope, action, receipt):
        if receipt["inputStopped"]:
            input_stopped()
        state = (
            "succeeded"
            if receipt["state"] == "succeeded"
            else "failed"
            if receipt["state"] in {"failed", "cancelled"}
            else "unknown"
        )
        result = self._result(receipt)
        await self.resources.finish(scope["owner"], action["id"], state, result)
        return state, result

    async def _perform(
        self,
        scope,
        resource,
        observed,
        binding,
        verb,
        args,
        *,
        browser_id,
        signature=None,
        phase="act",
    ):
        action = await self.resources.begin(
            scope["owner"],
            resource["id"],
            scope["taskId"],
            scope["runId"],
            observed.get("lease_epoch", resource["lease_epoch"]),
            observed["id"],
            observed["sceneEpoch"],
            {"verb": verb, "args": args, "browserId": browser_id, "signature": signature},
            binding["turnId"] + ":" + binding["toolCallId"] + ":" + phase,
        )
        if not action["dispatch"]:
            if action["state"] != "succeeded":
                raise DomainError("TOOL_OUTCOME_UNKNOWN")
            return json.loads(action["result_json"])
        receipt = None
        try:
            input_started()
            receipt = self._receipt(
                await self._cli(
                    verb,
                    *args,
                    operation_id=action["id"],
                    browser_id=browser_id,
                    signature=signature,
                ),
                action["id"],
            )
        except (DomainError, OSError, TimeoutError, asyncio.CancelledError) as exc:
            try:
                async with asyncio.timeout(3):
                    receipt = self._receipt(
                        await self._cli("operation-cancel", operation_id=action["id"]), action["id"]
                    )
            except (DomainError, OSError, TimeoutError, asyncio.CancelledError):
                receipt = None
            if receipt:
                await self._complete(scope, action, receipt)
            else:
                await self.resources.finish(
                    scope["owner"],
                    action["id"],
                    "unknown",
                    {
                        "inputStopped": False,
                        "outcomeKnown": False,
                        "error": "BROWSER_OPERATION_INTERRUPTED",
                    },
                )
            if isinstance(exc, asyncio.CancelledError):
                raise ToolCancellation(
                    input_stopped=bool(receipt and receipt["inputStopped"])
                ) from None
            if not receipt or receipt["state"] not in {"succeeded", "failed", "cancelled"}:
                raise DomainError("TOOL_OUTCOME_UNKNOWN") from None
        state, result = await self._complete(scope, action, receipt)
        if state == "unknown":
            raise DomainError("TOOL_OUTCOME_UNKNOWN")
        if state != "succeeded":
            raise DomainError(receipt.get("errorCode") or "BROWSER_ACTION_FAILED", 409)
        return result

    @passive_cancel_boundary
    async def open(self, args, binding):
        scope = await self.resources.scope(binding, input_action=True)
        capabilities = await self.capabilities()
        browser_id = capabilities["browserId"]
        target_id = args.get("targetId")
        if target_id:
            if not self.config.get("existing_tabs", False):
                raise DomainError("BROWSER_TARGET_SCOPE_REQUIRED", 409)
            if args.get("url"):
                raise DomainError("BROWSER_TARGET_OPTIONS_CONFLICT")
        else:
            url = args.get("url", "about:blank")
            parsed = urlsplit(url)
            if url != "about:blank" and (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise DomainError("BROWSER_URL_INVALID")
            lease = await self._claim(scope, "browser:" + browser_id + ":context", binding=binding)
            observed = await self.resources.observe(
                scope["owner"],
                lease["id"],
                scope["taskId"],
                scope["runId"],
                lease["lease_epoch"],
                hashlib.sha256(browser_id.encode()).hexdigest(),
                {"browserId": browser_id},
            )
            try:
                owned = await self.resources.owned(scope)
                if (
                    sum(":target:" in item["resource_key"] for item in owned)
                    >= self.config["max_tabs"]
                ):
                    raise DomainError("BROWSER_TAB_BUDGET_EXCEEDED", 409)
                result = await self._perform(
                    scope,
                    lease,
                    observed,
                    binding,
                    "new",
                    [],
                    browser_id=browser_id,
                    phase="create",
                )
                target_id = json.loads(result["output"])["targetId"]
            finally:
                try:
                    await self.resources.release(
                        scope["owner"],
                        lease["id"],
                        scope["taskId"],
                        scope["runId"],
                        lease["lease_epoch"],
                    )
                except DomainError:
                    pass
        if not isinstance(target_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", target_id):
            raise DomainError("BROWSER_DRIVER_PROTOCOL_INVALID", 503)
        lease = await self._claim(
            scope,
            "browser:" + browser_id + ":target:" + target_id,
            created=not args.get("targetId"),
            binding=binding,
        )
        try:
            opened = await self.observe({"resourceId": lease["id"]}, binding)
        except (DomainError, OSError):
            return {
                "resourceId": lease["id"],
                "opened": True,
                "navigationPending": not args.get("targetId") and url != "about:blank",
                "error": "BROWSER_OBSERVATION_UNAVAILABLE",
            }
        if not args.get("targetId") and url != "about:blank":
            return await self.act(
                {"observationId": opened["observation"]["id"], "kind": "goto", "url": url},
                binding,
                phase="navigate",
            )
        return opened

    @passive_cancel_boundary
    async def observe(self, args, binding):
        scope = await self.resources.scope(binding)
        resource = await self.resources.resource(scope, args["resourceId"])
        browser_id, target_id = self._target(resource)
        resource = await self._claim(scope, resource["resource_key"], binding=binding)
        path = self.captures / (identity() + ".png")
        try:
            try:
                body = await self._cli(
                    "observe",
                    "--target",
                    target_id,
                    "--screenshot",
                    str(path),
                    browser_id=browser_id,
                )
            except DomainError as exc:
                if exc.code not in {"CHROME_OBSERVATION_TIMEOUT", "CHROME_SCENE_CHANGED"}:
                    raise
                body = await self._cli("observe", "--target", target_id, browser_id=browser_id)
                body, _ = self._observation(body, None)
                body["screenshotError"] = exc.code
                observed = await self.resources.observe(
                    scope["owner"],
                    resource["id"],
                    scope["taskId"],
                    scope["runId"],
                    resource["lease_epoch"],
                    body["signature"],
                    body,
                )
                return {"observation": self._view(observed), "artifactRefs": []}
            body, screenshot = self._observation(body, path)
            image = await asyncio.to_thread(self._read_capture, path, self.artifacts.max_bytes)
            if (
                image[:8] != b"\x89PNG\r\n\x1a\n"
                or len(image) < 24
                or struct.unpack(">II", image[16:24]) != (screenshot["width"], screenshot["height"])
            ):
                raise DomainError("BROWSER_SCREENSHOT_INVALID", 503)
            artifact = await self.artifacts.put(
                scope["owner"],
                image,
                mime_type="image/png",
                name="browser-observation.png",
                task_id=scope["taskId"],
                message_id=binding.get("assistantMessageId"),
                metadata={
                    "source": "browser",
                    "resourceId": resource["id"],
                    "signature": body["signature"],
                    **screenshot,
                },
            )
            body.update(screenshotRef=artifact["id"], screenshot=screenshot)
            observed = await self.resources.observe(
                scope["owner"],
                resource["id"],
                scope["taskId"],
                scope["runId"],
                resource["lease_epoch"],
                body["signature"],
                body,
            )
            return {"observation": self._view(observed), "artifactRefs": [artifact]}
        finally:
            await asyncio.to_thread(path.unlink, missing_ok=True)

    @passive_cancel_boundary
    async def act(self, args, binding, *, phase="act"):
        scope = await self.resources.scope(binding, input_action=True)
        observed = await self.resources.observation(scope, args["observationId"])
        resource = await self.resources.resource(scope, observed["resource_id"])
        browser_id, target_id = self._target(resource)
        body = json.loads(observed["body_json"])
        choice = args["kind"]
        arguments = ["--target", target_id]
        if choice in {"click", "fill", "type"}:
            arguments += [args["selector"]]
        if choice in {"fill", "type"}:
            arguments += [args["text"]]
        if choice == "press":
            arguments += [args["key"]]
        if choice == "goto":
            parsed = urlsplit(args["url"])
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise DomainError("BROWSER_URL_INVALID")
            arguments += [args["url"]]
        result = await self._perform(
            scope,
            resource,
            {
                "id": observed["id"],
                "sceneEpoch": observed["scene_epoch"],
                "lease_epoch": observed["lease_epoch"],
            },
            binding,
            choice,
            arguments,
            browser_id=browser_id,
            signature=body["signature"],
            phase=phase,
        )
        try:
            after = await self.observe({"resourceId": resource["id"]}, binding)
            return {
                **after,
                "action": {"operationId": result["operationId"], "state": "succeeded"},
                "needsVerification": True,
            }
        except (DomainError, OSError, KeyError):
            return {
                "resourceId": resource["id"],
                "action": {"operationId": result["operationId"], "state": "succeeded"},
                "needsVerification": True,
                "error": "BROWSER_OBSERVATION_UNAVAILABLE",
            }
