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
        return {t["targetId"]: t for t in targets}

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
        if isinstance(live, dict):
            for target_id, meta in live.items():
                if meta.get("origin") not in {"human", "agent"}:
                    continue
                rid = await self.track("local", browser_id, target_id)
                timestamp = meta.get("lastUsedAt", now_ms())
                await self.db.call(
                    lambda db, rid=rid, meta=meta, timestamp=timestamp: db.execute(
                        "UPDATE browser_tabs SET catalog_used_ms=?,origin=?,protected=?,sleeping=?,sleep_after_seconds=?,close_after_seconds=?,"
                        "last_used_ms=MAX(last_used_ms,?),idle_since_ms=CASE WHEN idle_since_ms IS NOT NULL THEN MAX(idle_since_ms,?) ELSE NULL END "
                        "WHERE resource_id=?",
                        (
                            timestamp,
                            meta["origin"],
                            int(bool(meta.get("pinned") or meta.get("busy"))),
                            int(bool(meta.get("sleeping"))),
                            meta.get(
                                "sleepAfterSeconds", 120 if meta["origin"] == "agent" else 1800
                            ),
                            meta.get("closeAfterSeconds", 600 if meta["origin"] == "agent" else 0),
                            timestamp,
                            timestamp,
                            rid,
                        ),
                    ),
                    write=True,
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
                if tab["catalog_used_ms"] and receipt["state"] in {
                    "succeeded",
                    "failed",
                    "cancelled",
                }:
                    await self.driver._cli(
                        "_tab-event",
                        encoded(
                            {
                                "action": "finish",
                                "browserId": browser_id,
                                "targetId": tab["target_id"],
                                "token": tab["close_operation_id"],
                                "known": True,
                                "sleeping": receipt["state"] == "succeeded"
                                and tab["maintenance_verb"] == "sleep",
                            }
                        ),
                    )
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
            if (
                receipt["state"] in {"failed", "cancelled"} and receipt["inputStopped"] is True
            ) or (receipt["state"] == "succeeded" and tab["maintenance_verb"] == "sleep"):
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
        if (
            accepted
            and receipt["state"] == "succeeded"
            and await self.db.call(
                lambda db: row(
                    db,
                    "SELECT maintenance_verb FROM browser_tabs WHERE resource_id=?",
                    (resource_id,),
                )["maintenance_verb"]
            )
            == "close"
        ):
            await self.closed(resource_id)

    async def recycle(self, resource_id, browser_id, *, verb="close"):
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
                or tab["protected"]
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
                "UPDATE browser_tabs SET state='closing',close_operation_id=?,close_receipt_json=NULL,maintenance_verb=? WHERE resource_id=?",
                (operation, verb, resource_id),
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
                        verb,
                        "--expected-origin",
                        tab["origin"],
                        *(
                            ["--expected-last-used", str(tab["catalog_used_ms"])]
                            if tab["catalog_used_ms"]
                            else []
                        ),
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

    async def candidates(self, browser_id, *, expired=False, sleeping=False):
        policy = (
            " AND b.sleep_after_seconds>0 AND b.sleeping=0 AND b.idle_since_ms<=?-b.sleep_after_seconds*1000"
            if sleeping
            else " AND b.close_after_seconds>0 AND b.idle_since_ms<=?-b.close_after_seconds*1000"
            if expired
            else " AND b.origin='agent' AND b.close_after_seconds>0"
        )
        return await self.db.call(
            lambda db: rows(
                db,
                "SELECT b.resource_id FROM browser_tabs b JOIN resources r ON r.id=b.resource_id "
                "WHERE b.browser_id=? AND b.state='open' AND b.protected=0 AND b.idle_since_ms<=? AND b.retry_after_ms<=? "
                "AND r.state='idle' AND r.owner_task_id IS NULL AND r.owner_run_id IS NULL "
                "AND NOT EXISTS(SELECT 1 FROM resource_actions a WHERE a.resource_id=r.id AND a.state IN ('running','unknown')) "
                + policy
                + " ORDER BY b.idle_since_ms,b.last_used_ms,b.created_ms,b.resource_id LIMIT 20",
                (browser_id, now_ms(), now_ms(), *([now_ms()] if expired or sleeping else [])),
            )
        )

    def capacity(self, capabilities):
        value = capabilities.get("tabPolicies", {}).get("agent", {}).get("maxTabs")
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1000:
            return value
        return self.driver.config["max_tabs"]

    async def make_room(self, capabilities):
        browser_id = capabilities["browserId"]
        live = await self.inventory(browser_id)
        await self.sync(browser_id, live)
        count = await self.db.call(
            lambda db: row(
                db,
                "SELECT COUNT(*) AS n FROM browser_tabs WHERE browser_id=? AND origin='agent' AND state!='closed'",
                (browser_id,),
            )["n"]
        )
        limit = self.capacity(capabilities)
        if limit == 0 or count < limit:
            return
        if "background_tab_close" in capabilities["features"]:
            for candidate in await self.candidates(browser_id):
                if await self.recycle(candidate["resource_id"], browser_id):
                    count -= 1
                    if count < limit:
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
        async with self.lock:
            try:
                async with asyncio.timeout(6):
                    capabilities = await self.driver.capabilities(no_start=True)
            except (DomainError, OSError, TimeoutError):
                return
            if "background_tab_close" not in capabilities.get("features", []):
                return
            browser_id = capabilities["browserId"]
            await self.sync(browser_id, await self.inventory(browser_id))
            for candidate in (await self.candidates(browser_id, expired=True))[:3]:
                await self.recycle(candidate["resource_id"], browser_id)
            if "background_tab_sleep" in capabilities.get("features", []):
                for candidate in (await self.candidates(browser_id, sleeping=True))[:3]:
                    await self.recycle(candidate["resource_id"], browser_id, verb="sleep")
