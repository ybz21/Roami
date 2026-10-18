"""Instance-local provider settings; HTTP views never contain credential material."""

import asyncio
import json
import os
import stat
import tempfile
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

import httpx

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.model_routes import ModelRoute
from roami_agent.protocol.models import model_endpoint

KEY_NAMES = {"main": "ROAMI_AGENT_SAVED_MAIN_KEY", "worker": "ROAMI_AGENT_SAVED_WORKER_KEY"}


class RuntimeSettings:
    def __init__(self, current):
        self.current = current
        self.updating = False

    def __getattr__(self, name):
        return getattr(self.current, name)


def settings_path(root):
    return Path(root) / "agents" / "model-settings.json"


def read_saved(root):
    path = settings_path(root)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {}
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_mode & 0o077
        or info.st_uid != os.getuid()
        or info.st_size > 32_000
    ):
        raise DomainError("MODEL_SETTINGS_PRIVATE_FILE_REQUIRED", 503)
    try:
        saved = json.loads(path.read_text())
        if not isinstance(saved, dict) or set(saved) - {"main", "worker"}:
            raise ValueError
        return saved
    except (ValueError, OSError):
        raise DomainError("MODEL_SETTINGS_INVALID", 503) from None


def effective_settings(base, saved, *, credentials=True):
    routes = {}
    for role in ("main", "worker"):
        old = base.route(role)
        value = saved.get(role, {})
        if not isinstance(value, dict) or set(value) - {"baseUrl", "model", "apiKey", "images"}:
            raise DomainError("INVALID_MODEL_CONFIG")
        if any(
            key in value and not isinstance(value[key], str)
            for key in ("baseUrl", "model", "apiKey")
        ):
            raise DomainError("INVALID_MODEL_CONFIG")
        endpoint = model_endpoint(value.get("baseUrl", old.endpoint).strip())
        name = value.get("model", old.name).strip()
        key_env = KEY_NAMES[role] if value.get("apiKey") else old.key_env
        if credentials and value.get("apiKey"):
            os.environ[key_env] = value["apiKey"]
        if (
            not name
            or len(name) > 200
            or not endpoint
            or type(value.get("images", False)) is not bool
        ):
            raise DomainError("INVALID_MODEL_CONFIG")
        capabilities = dict(old.capabilities)
        if "images" in value:
            capabilities["images"] = value["images"]
        routes[role] = ModelRoute(
            endpoint,
            name,
            key_env,
            old.timeout_seconds,
            old.max_retries,
            capabilities,
            old.cache,
            old.parameters,
        )
    main, worker = routes["main"], routes["worker"]
    return replace(
        base,
        endpoint=main.endpoint,
        model=main.name,
        key_env=main.key_env,
        model_capabilities=main.capabilities,
        worker_route=worker,
        extra_key_envs=tuple(sorted(base.provider_key_environments())),
    )


def load_model_settings(base, root):
    saved = read_saved(root)
    return effective_settings(base, saved) if saved else base


class ModelSettings:
    def __init__(self, runtime, factory):
        self.runtime, self.factory = runtime, factory
        self.lock = asyncio.Lock()
        self.base = runtime.settings.current
        self.saved = read_saved(runtime.db.data_root)
        self.owned_providers = []

    @staticmethod
    def owner(owner):
        if owner != "local":
            raise DomainError("MODEL_SETTINGS_FORBIDDEN", 403)

    def view(self, owner):
        self.owner(owner)
        return {
            role: {
                "baseUrl": self.runtime.settings.route(role).endpoint,
                "model": self.runtime.settings.route(role).name,
                "keyConfigured": bool(self.runtime.settings.credentials(role)),
                "images": self.runtime.settings.route(role).capabilities.get("images") is True,
            }
            for role in ("main", "worker")
        }

    def merge(self, patch):
        if not isinstance(patch, dict) or not patch or set(patch) - {"main", "worker"}:
            raise DomainError("INVALID_MODEL_CONFIG")
        saved = {role: dict(value) for role, value in self.saved.items()}
        for role, changes in patch.items():
            if not isinstance(changes, dict) or set(changes) - {
                "baseUrl",
                "model",
                "apiKey",
                "images",
            }:
                raise DomainError("INVALID_MODEL_CONFIG")
            item = saved.setdefault(role, {})
            for key, value in changes.items():
                if key == "images":
                    if type(value) is not bool:
                        raise DomainError("INVALID_MODEL_CONFIG")
                elif (
                    not isinstance(value, str)
                    or len(value) > (4096 if key == "apiKey" else 2000)
                    or any(ord(c) < 32 for c in value)
                ):
                    raise DomainError("INVALID_MODEL_CONFIG")
                if key == "apiKey" and not value.strip():
                    continue
                item[key] = value.strip() if isinstance(value, str) else value
        return saved

    def _prepare(self, saved):
        path = settings_path(self.runtime.db.data_root)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = path.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise DomainError("MODEL_SETTINGS_PRIVATE_FILE_REQUIRED", 503)
        descriptor, temporary = tempfile.mkstemp(prefix=".model-settings-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w") as file:
                os.fchmod(file.fileno(), 0o600)
                json.dump(saved, file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            return temporary
        except BaseException:
            os.unlink(temporary)
            raise

    async def save(self, owner, patch):
        self.owner(owner)
        async with self.lock:
            saved = self.merge(patch)
            for role, change in patch.items():
                route = self.runtime.settings.route(role)
                if (
                    change.get("baseUrl", route.endpoint).rstrip("/") != route.endpoint
                    and self.runtime.settings.credentials(role)
                    and not change.get("apiKey")
                ):
                    raise DomainError("MODEL_KEY_REQUIRED_FOR_ENDPOINT")
            effective_settings(self.base, saved, credentials=False)
            self.runtime.reconfiguring = True
            self.runtime.settings.updating = True
            temporary = None
            candidates = []
            published = False
            old_keys = {name: os.environ.get(name) for name in KEY_NAMES.values()}
            try:
                busy = await self.runtime.db.call(
                    lambda db: db.execute(
                        "SELECT 1 FROM jobs WHERE state='running' LIMIT 1"
                    ).fetchone()
                )
                if (
                    busy
                    or self.runtime.turn_tasks
                    or self.runtime.active
                    or self.runtime.briefs.lock.locked()
                    or self.runtime.proactive.lock.locked()
                ):
                    raise DomainError("MODEL_CONFIGURATION_BUSY", 409)
                prepare = asyncio.create_task(asyncio.to_thread(self._prepare, saved))
                try:
                    temporary = await asyncio.shield(prepare)
                except asyncio.CancelledError:
                    temporary = await prepare
                    raise
                settings = effective_settings(self.base, saved)
                for role in ("main", "worker"):
                    candidates.append(self.factory(settings, role))
                main, worker = candidates
                path = settings_path(self.runtime.db.data_root)
                os.replace(temporary, path)
                temporary = None
                directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                runtime = self.runtime
                runtime.settings.current = settings
                runtime.model, runtime.worker_model = main, worker
                runtime.loop.model, runtime.loop.worker_model = main, worker
                from roami_agent.context.vision_inputs import VisionInputs

                runtime.loop.context.vision = (
                    VisionInputs(runtime.db, runtime.artifacts)
                    if settings.route("worker").capabilities.get("images") is True
                    else None
                )
                runtime.chat.model, runtime.context.model = main, main
                if runtime.memory_uses_worker:
                    runtime.memory_jobs.model = worker
                runtime.briefs.model, runtime.proactive.model = worker, worker
                self.saved = saved
                published = True
                previous = self.owned_providers
                self.owned_providers = [main, worker]
                for provider in previous:
                    with suppress(Exception):
                        await provider.close()
                return self.view(owner)
            finally:
                if not published:
                    for name, value in old_keys.items():
                        if value is None:
                            os.environ.pop(name, None)
                        else:
                            os.environ[name] = value
                    for provider in candidates:
                        with suppress(Exception):
                            await provider.close()
                self.runtime.reconfiguring = False
                self.runtime.settings.updating = False
                self.runtime.wakeup.set()
                if temporary:
                    os.unlink(temporary)

    async def models(self, owner, role="main", patch=None):
        self.owner(owner)
        if role not in {"main", "worker"}:
            raise DomainError("INVALID_MODEL_CONFIG")
        route = self.runtime.settings.route(role)
        supplied = (patch or {}).get(role, {})
        if patch:
            self.merge(patch)
            candidate = replace(
                route, endpoint=model_endpoint(supplied.get("baseUrl", route.endpoint).strip())
            )
            if (
                candidate.endpoint != route.endpoint
                and self.runtime.settings.credentials(role)
                and not supplied.get("apiKey")
            ):
                raise DomainError("MODEL_KEY_REQUIRED_FOR_ENDPOINT")
            route = candidate
        if not route.endpoint:
            raise DomainError("MODEL_NOT_CONFIGURED", 503)
        key = supplied.get("apiKey") or self.runtime.settings.credentials(role)
        headers = {"Authorization": "Bearer " + key} if key else {}
        try:
            async with (
                httpx.AsyncClient(timeout=8, follow_redirects=False) as client,
                client.stream(
                    "GET", route.endpoint.rstrip("/") + "/models", headers=headers
                ) as response,
            ):
                if response.status_code != 200:
                    raise DomainError("MODEL_PROVIDER_UNAVAILABLE", 502)
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 2 * 1024 * 1024:
                        raise DomainError("MODEL_CATALOG_LIMIT", 502)
            value = json.loads(data)
            names = sorted(
                {
                    item["id"]
                    for item in value["data"]
                    if isinstance(item, dict)
                    and isinstance(item.get("id"), str)
                    and 0 < len(item["id"]) <= 200
                }
            )
            return {"models": names[:200], "truncated": len(names) > 200}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise DomainError("MODEL_PROVIDER_UNAVAILABLE", 502) from None

    async def close(self):
        for provider in self.owned_providers:
            await provider.close()
