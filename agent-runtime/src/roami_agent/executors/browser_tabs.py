"""A durable pool of Agent-created tabs, with fenced idle-only recycling."""

import asyncio
import re
import time

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row, rows


class BrowserTabs:
    def __init__(self, driver):
        self.driver, self.db, self.resources = driver, driver.db, driver.resources
        self.lock = asyncio.Lock()
        self.next_sweep = 0

    async def track(self, owner, browser_id, target_id, *, created_ms=None):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", target_id):
            raise DomainError("BROWSER_DRIVER_PROTOCOL_INVALID", 503)
        key = f"browser:{browser_id}:target:{target_id}"
        timestamp = now_ms()

        def write(db):
            db.execute(
                "INSERT OR IGNORE INTO resources(id,node_id,kind,resource_key,owner_id,created_by_task) "
                "VALUES(?,'local','browser',?,?,1)",
                (identity(), key, owner),
            )
            resource = row(
                db,
                "SELECT * FROM resources WHERE node_id='local' AND kind='browser' AND resource_key=?",
                (key,),
            )
            db.execute(
                "INSERT OR IGNORE INTO browser_tabs(resource_id,browser_id,target_id,created_ms,last_used_ms,idle_since_ms) "
                "VALUES(?,?,?,?,?,?)",
                (
                    resource["id"],
                    browser_id,
                    target_id,
                    created_ms or timestamp,
                    timestamp,
                    timestamp
                    if resource["state"] == "idle" and not resource["owner_task_id"]
                    else None,
                ),
            )
            return resource["id"]

        return await self.db.call(write, write=True)

    async def inventory(self, browser_id):
        async with asyncio.timeout(6):
            targets = await self.driver._cli(
                "tabs", "--no-start", browser_id=browser_id, readiness_wait_ms=3000
            )
        if not isinstance(targets, list) or any(
            not isinstance(t, dict) or not isinstance(t.get("targetId"), str) for t in targets
        ):
            raise DomainError("BROWSER_DRIVER_PROTOCOL_INVALID", 503)
        return {t["targetId"] for t in targets}

    async def sync(self, browser_id, live):
        # Successful create receipts are the only provenance accepted for pre-upgrade tabs.
        identifiers = list(live)
        for offset in range(0, len(identifiers), 200):
            chunk = identifiers[offset : offset + 200]
            proofs = await self.db.call(
                lambda db, chunk=chunk: rows(
                    db,
                    "SELECT * FROM (SELECT t.owner_id,a.created_ms,"
                    "CASE WHEN json_valid(json_extract(a.result_json,'$.output')) "
                    "THEN json_extract(json_extract(a.result_json,'$.output'),'$.targetId') END AS target_id "
                    "FROM resource_actions a JOIN tasks t ON t.id=a.task_id "
                    "WHERE a.state='succeeded' AND json_extract(a.action_json,'$.verb')='new' "
                    "AND json_extract(a.action_json,'$.browserId')=?) AS proof WHERE target_id IN ("
                    + ",".join("?" for _ in chunk)
                    + ") "
                    "AND NOT EXISTS(SELECT 1 FROM browser_tabs b WHERE b.browser_id=? AND b.target_id=proof.target_id)",
                    (browser_id, *chunk, browser_id),
                )
            )
            for proof in proofs:
                await self.track(
                    proof["owner_id"],
                    browser_id,
                    proof["target_id"],
                    created_ms=proof["created_ms"],
                )
        tracked = await self.db.call(
            lambda db: rows(
                db,
                "SELECT * FROM browser_tabs WHERE browser_id=? AND state!='closed'",
                (browser_id,),
            )
        )
        for tab in tracked:
            if tab["target_id"] not in live:
                await self.closed(tab["resource_id"])
            elif tab["state"] == "closing":
                try:
                    receipt = self.driver._receipt(
                        await self.driver.receipt_reader(tab["close_operation_id"]),
                        tab["close_operation_id"],
                    )
                except (DomainError, OSError, TimeoutError):
                    continue
                await self.finish(tab["resource_id"], receipt)

    async def closed(self, resource_id):
        def write(db):
            db.execute(
                "UPDATE browser_tabs SET state='closed',closed_ms=? WHERE resource_id=?",
                (now_ms(), resource_id),
            )
            db.execute(
                "UPDATE resources SET state='idle',owner_id=NULL,lease_until_ms=NULL,lease_epoch=lease_epoch+1 "
                "WHERE id=? AND owner_task_id IS NULL AND state IN ('idle','quarantined') "
                "AND NOT EXISTS(SELECT 1 FROM resource_actions a WHERE a.resource_id=resources.id AND a.state IN ('running','unknown'))",
                (resource_id,),
            )

        await self.db.call(write, write=True)

    async def finish(self, resource_id, receipt):
        def write(db):
            tab = row(
                db,
                "SELECT * FROM browser_tabs WHERE resource_id=? AND state='closing'",
                (resource_id,),
            )
            if not tab or tab["close_operation_id"] != receipt["id"]:
                return False
            db.execute(
                "UPDATE browser_tabs SET close_receipt_json=? WHERE resource_id=?",
                (encoded(receipt), resource_id),
            )
            if receipt["state"] in {"failed", "cancelled"} and receipt["inputStopped"] is True:
                db.execute(
                    "UPDATE browser_tabs SET state='open',retry_after_ms=? WHERE resource_id=?",
                    (now_ms() + 60_000, resource_id),
                )
                db.execute(
                    "UPDATE resources SET state='idle',lease_epoch=lease_epoch+1 WHERE id=? AND state='quarantined' AND owner_task_id IS NULL",
                    (resource_id,),
                )
            return True

        accepted = await self.db.call(write, write=True)
        if accepted and receipt["state"] == "succeeded":
            await self.closed(resource_id)

    async def recycle(self, resource_id, browser_id):
        operation = identity()

        def reserve(db):
            tab = row(
                db,
                "SELECT * FROM browser_tabs WHERE resource_id=? AND state='open' AND retry_after_ms<=?",
                (resource_id, now_ms()),
            )
            resource = row(db, "SELECT * FROM resources WHERE id=?", (resource_id,))
            if (
                not tab
                or tab["browser_id"] != browser_id
                or resource["state"] != "idle"
                or resource["owner_task_id"]
                or resource["owner_run_id"]
            ):
                return None
            if row(
                db,
                "SELECT id FROM resource_actions WHERE resource_id=? AND state IN ('running','unknown') LIMIT 1",
                (resource_id,),
            ):
                return None
            db.execute(
                "UPDATE browser_tabs SET state='closing',close_operation_id=?,close_receipt_json=NULL WHERE resource_id=?",
                (operation, resource_id),
            )
            db.execute(
                "UPDATE resources SET state='quarantined',lease_epoch=lease_epoch+1 WHERE id=?",
                (resource_id,),
            )
            return tab

        tab = await self.db.call(reserve, write=True)
        if not tab:
            return False
        try:
            async with asyncio.timeout(6):
                receipt = self.driver._receipt(
                    await self.driver._cli(
                        "close",
                        "--target",
                        tab["target_id"],
                        "--only-if-background",
                        "--no-start",
                        operation_id=operation,
                        browser_id=browser_id,
                        readiness_wait_ms=3000,
                    ),
                    operation,
                )
        except (DomainError, OSError, TimeoutError):
            return False
        await self.finish(resource_id, receipt)
        return receipt["state"] == "succeeded"

    async def candidates(self, browser_id, *, expired=False):
        cutoff = (
            now_ms() - self.driver.config.get("idle_timeout_seconds", 600) * 1000
            if expired
            else now_ms()
        )
        return await self.db.call(
            lambda db: rows(
                db,
                "SELECT b.resource_id FROM browser_tabs b JOIN resources r ON r.id=b.resource_id "
                "WHERE b.browser_id=? AND b.state='open' AND b.idle_since_ms<=? AND b.retry_after_ms<=? "
                "AND r.state='idle' AND r.owner_task_id IS NULL AND r.owner_run_id IS NULL "
                "AND NOT EXISTS(SELECT 1 FROM resource_actions a WHERE a.resource_id=r.id AND a.state IN ('running','unknown')) "
                "ORDER BY b.idle_since_ms,b.last_used_ms,b.created_ms,b.resource_id LIMIT 20",
                (browser_id, cutoff, now_ms()),
            )
        )

    async def make_room(self, capabilities):
        browser_id = capabilities["browserId"]
        live = await self.inventory(browser_id)
        await self.sync(browser_id, live)
        count = await self.db.call(
            lambda db: row(
                db,
                "SELECT COUNT(*) AS n FROM browser_tabs WHERE browser_id=? AND state!='closed'",
                (browser_id,),
            )["n"]
        )
        if count < self.driver.config["max_tabs"]:
            return
        if "background_tab_close" in capabilities["features"]:
            for candidate in await self.candidates(browser_id):
                if await self.recycle(candidate["resource_id"], browser_id):
                    count -= 1
                    if count < self.driver.config["max_tabs"]:
                        return
        raise DomainError("BROWSER_TAB_BUDGET_EXCEEDED", 409)

    async def sweep(self):
        if (
            not self.driver.config.get("enabled")
            or time.monotonic() < self.next_sweep
            or self.lock.locked()
        ):
            return
        self.next_sweep = time.monotonic() + 30
        if not await self.db.call(
            lambda db: row(
                db,
                "SELECT resource_id AS id FROM browser_tabs WHERE state!='closed' UNION ALL "
                "SELECT id FROM resources WHERE kind='browser' AND created_by_task=1 "
                "AND NOT EXISTS(SELECT 1 FROM browser_tabs b WHERE b.resource_id=resources.id) LIMIT 1",
            )
        ):
            return
        async with self.lock:
            async with asyncio.timeout(6):
                capabilities = await self.driver.capabilities(no_start=True)
            if "background_tab_close" not in capabilities.get("features", []):
                return
            browser_id = capabilities["browserId"]
            await self.sync(browser_id, await self.inventory(browser_id))
            for candidate in (await self.candidates(browser_id, expired=True))[:3]:
                await self.recycle(candidate["resource_id"], browser_id)
