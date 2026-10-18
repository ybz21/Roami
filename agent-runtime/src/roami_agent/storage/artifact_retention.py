"""Bounded reclamation of deleted evidence and abandoned private writes."""

import os
import re
import stat

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import row, rows


class ArtifactRetention:
    def __init__(self, artifacts, *, grace_seconds=86400, batch_size=100, interval_seconds=300):
        if (
            not isinstance(grace_seconds, int)
            or isinstance(grace_seconds, bool)
            or not 3600 <= grace_seconds <= 365 * 86400
            or not isinstance(batch_size, int)
            or isinstance(batch_size, bool)
            or not 1 <= batch_size <= 100
            or not isinstance(interval_seconds, int)
            or isinstance(interval_seconds, bool)
            or not 10 <= interval_seconds <= 3600
        ):
            raise DomainError("INVALID_ARTIFACT_RETENTION_CONFIG")
        self.artifacts = artifacts
        self.db = artifacts.db
        self.grace_ms = grace_seconds * 1000
        self.batch_size = batch_size
        self.interval_seconds = interval_seconds
        self.prefix = 0
        self.last_digest = ""
        self.scan = None
        self.scan_prefix = None
        self.closed = False

    def _scan_batch(self):
        candidates, visited, examined = [], 0, 0
        while examined < self.batch_size and visited < 16:
            if self.scan is None:
                prefix = f"{self.prefix:02x}"
                self.prefix = (self.prefix + 1) % 256
                visited += 1
                try:
                    directory = self.artifacts._path(prefix + "0" * 62).parent
                    self.scan = os.scandir(directory)
                    self.scan_prefix = prefix
                except FileNotFoundError:
                    continue
            try:
                entry = next(self.scan)
            except StopIteration:
                self.scan.close()
                self.scan = None
                continue
            examined += 1
            digest = None
            if re.fullmatch(r"[0-9a-f]{64}\.blob", entry.name):
                digest = entry.name[:-5]
                if not digest.startswith(self.scan_prefix):
                    continue
            elif not re.fullmatch(r"\.artifact-[a-z0-9_]{8}", entry.name):
                continue
            try:
                info = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode):
                candidates.append((self.scan_prefix, entry.name, digest, self._fingerprint(info)))
        return candidates

    @staticmethod
    def _fingerprint(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def _unlink(self, prefix, name, expected=None):
        directory = self.artifacts._path(prefix + "0" * 62).parent
        path = directory / name
        try:
            info = path.lstat()
        except FileNotFoundError:
            return 0 if expected is None else None
        if not stat.S_ISREG(info.st_mode):
            raise DomainError("ARTIFACT_PATH_INVALID", 503)
        if expected is not None and self._fingerprint(info) != expected:
            return None
        path.unlink()
        self.artifacts._sync_directory(directory)
        return info.st_size

    async def collect(self):
        if self.closed:
            raise DomainError("ARTIFACT_RETENTION_CLOSED", 503)
        summary = {"purgedBlobs": 0, "orphanFiles": 0, "reclaimedBytes": 0, "errors": 0}
        cutoff = now_ms() - self.grace_ms
        async with self.artifacts.mutations:
            if self.closed:
                raise DomainError("ARTIFACT_RETENTION_CLOSED", 503)
            candidates = await self.db.call(
                lambda db: rows(
                    db,
                    "SELECT DISTINCT a.sha256 FROM artifacts a "
                    "WHERE a.deleted_ms<? AND a.purged_ms IS NULL AND a.sha256>? "
                    "AND length(a.sha256)=64 AND a.sha256 NOT GLOB '*[^0-9a-f]*' "
                    "AND a.path='agent-artifacts/blobs/'||substr(a.sha256,1,2)||'/'||a.sha256||'.blob' "
                    "AND NOT EXISTS(SELECT 1 FROM artifacts r WHERE r.sha256=a.sha256 "
                    "AND (r.deleted_ms IS NULL OR r.deleted_ms>=?)) "
                    "ORDER BY a.sha256 LIMIT ?",
                    (cutoff, self.last_digest, cutoff, self.batch_size),
                )
            )
            for candidate in candidates:
                digest = candidate["sha256"]
                try:
                    reclaimed = await self.artifacts._io(self._unlink, digest[:2], digest + ".blob")
                except FileNotFoundError:
                    reclaimed = 0
                except (OSError, DomainError):
                    summary["errors"] += 1
                    continue
                await self.db.call(
                    lambda db, digest=digest: db.execute(
                        "UPDATE artifacts SET purged_ms=? WHERE sha256=? "
                        "AND deleted_ms<? AND purged_ms IS NULL "
                        "AND path='agent-artifacts/blobs/'||substr(sha256,1,2)||'/'||sha256||'.blob'",
                        (now_ms(), digest, cutoff),
                    ),
                    write=True,
                )
                summary["purgedBlobs"] += 1
                summary["reclaimedBytes"] += reclaimed
            self.last_digest = candidates[-1]["sha256"] if candidates else ""
            try:
                scanned = await self.artifacts._io(self._scan_batch)
            except (OSError, DomainError):
                scanned = []
                summary["errors"] += 1
            for prefix, name, digest, fingerprint in scanned:
                if max(fingerprint[3:]) >= cutoff * 1_000_000:
                    continue
                if digest and await self.db.call(
                    lambda db, digest=digest: row(
                        db,
                        "SELECT 1 FROM artifacts WHERE sha256=? "
                        "AND (deleted_ms IS NULL OR purged_ms IS NULL) LIMIT 1",
                        (digest,),
                    )
                ):
                    continue
                try:
                    reclaimed = await self.artifacts._io(self._unlink, prefix, name, fingerprint)
                except FileNotFoundError:
                    continue
                except (OSError, DomainError):
                    summary["errors"] += 1
                    continue
                if reclaimed is not None:
                    summary["orphanFiles"] += 1
                    summary["reclaimedBytes"] += reclaimed
        return summary

    def _close_scan(self):
        if self.scan is not None:
            self.scan.close()
            self.scan = None

    async def close(self):
        if self.closed:
            return
        self.closed = True
        await self.artifacts._io(self._close_scan)
