"""Reconcile outstanding receipts from installations that used native browser control."""

import asyncio
import json
import os
import re
import stat

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import event, rows


class LegacyBrowserReceipts:
    def __init__(self, database, resources):
        self.db, self.resources = database, resources
        self.root = database.data_root.resolve()
        self.receipts = self.root / "agents/browser-operations"
        self.reconcile_cursor = ""

    async def pending(self):
        return await self.db.call(
            lambda db: db.execute(
                "SELECT EXISTS(SELECT 1 FROM resource_actions a JOIN resources r ON r.id=a.resource_id "
                "WHERE r.kind='browser' AND a.state='unknown' "
                "AND COALESCE(json_extract(a.result_json,'$.inputStopped'),0)!=1)"
            ).fetchone()[0]
        )

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
                receipt = json.load(file)
            except (ValueError, TypeError):
                raise DomainError("BROWSER_DRIVER_PROTOCOL_INVALID", 503) from None
        receipt = self._receipt(receipt, operation_id)
        if not isinstance(receipt, dict) or receipt.get("state") not in {"accepted", "running"}:
            return receipt
        try:
            descriptor = os.open(
                self.receipts / (operation_id + ".lock"),
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            )
            with os.fdopen(descriptor, "rb") as lock:
                info = os.fstat(lock.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_mode & 0o077
                    or info.st_size > 32
                ):
                    return receipt
                owner = lock.read(32)
            if not re.fullmatch(rb"[1-9][0-9]{0,9}", owner):
                return receipt
            pid = int(owner)
            if pid > 2**31 - 1:
                return receipt
            os.kill(pid, 0)
        except ProcessLookupError:
            # Process exit proves input stopped, never that a submitted action succeeded.
            return {
                **receipt,
                "state": "unknown",
                "inputStopped": True,
                "outcomeKnown": False,
                "errorCode": "CHROME_OPERATION_DRIVER_EXITED",
                "stopEvidence": {"kind": "driver_process_exited", "pid": pid},
            }
        except OSError:
            pass
        return receipt

    async def reconcile(self):
        pending = await self.db.call(
            lambda db: rows(
                db,
                "SELECT a.*,r.owner_id,r.resource_key,t.origin_conversation_id FROM resource_actions a "
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
                receipt = await asyncio.to_thread(self._read_receipt_file, action["id"])
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
            **({"stopEvidence": receipt["stopEvidence"]} if receipt.get("stopEvidence") else {}),
        }

    async def _complete(self, scope, action, receipt):
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
