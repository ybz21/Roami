"""Readiness evidence bound to the saved routes, including credential changes."""

import asyncio
import hashlib
import json
import os
import stat
import tempfile
from contextlib import suppress
from pathlib import Path

from roami_agent.protocol.errors import DomainError


def route_fingerprint(settings, role):
    route = settings.route(role)
    material = {
        "endpoint": route.endpoint,
        "name": route.name,
        "parameters": route.parameters,
        "capabilities": route.capabilities,
        "contextWindow": route.context_window,
        "credential": settings.credentials(role),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def verification_path(root):
    return Path(root) / "agents" / "model-verification.json"


def catalog_revision(settings, root):
    try:
        fingerprints = json.loads((Path(root) / "agents" / "model-catalog-revision").read_text())
    except FileNotFoundError:
        fingerprints = {}
    return json.dumps(
        {role: fingerprints.get(settings.route(role).name, "") for role in ("main", "worker")},
        sort_keys=True,
    )


def verified_routes(settings, root):
    path = verification_path(root)
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_uid != os.getuid()
            or info.st_size > 4096
        ):
            return False
        proof = json.loads(path.read_text())
        return proof.get("catalog", "") == catalog_revision(settings, root) and all(
            proof.get(role) == route_fingerprint(settings, role) for role in ("main", "worker")
        )
    except (OSError, ValueError, AttributeError):
        return False


async def verify_models(manager, owner):
    manager.owner(owner)
    async with manager.lock:
        settings = manager.runtime.settings
        path = verification_path(manager.runtime.db.data_root)
        revision = catalog_revision(settings, manager.runtime.db.data_root)
        with suppress(FileNotFoundError):
            path.unlink()
        checked = set()
        for role, provider in (
            ("main", manager.runtime.model),
            ("worker", manager.runtime.worker_model),
        ):
            identity = route_fingerprint(settings, role)
            if identity in checked:
                continue
            received = False
            stream = provider.stream([{"role": "user", "content": "Reply with OK."}], [])
            try:
                async with asyncio.timeout(45):
                    async for event in stream:
                        if event.kind == "text" and event.value:
                            received = True
            except TimeoutError:
                raise DomainError("MODEL_VERIFICATION_TIMEOUT", 504) from None
            finally:
                await stream.aclose()
            if not received:
                raise DomainError("MODEL_VERIFICATION_EMPTY", 502)
            checked.add(identity)
        proof = {role: route_fingerprint(settings, role) for role in ("main", "worker")}
        if catalog_revision(settings, manager.runtime.db.data_root) != revision:
            raise DomainError("MODEL_CATALOG_CHANGED", 409)
        proof["catalog"] = revision
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".model-verification-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w") as output:
                json.dump(proof, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary)
        return manager.view(owner)
