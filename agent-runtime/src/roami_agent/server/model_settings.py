"""Instance-local provider settings; HTTP views never contain credential material."""

import asyncio
import json
import os
import stat
import tempfile
from contextlib import suppress
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.improvement import policy_value
from roami_agent.protocol.model_routes import ModelRoute
from roami_agent.protocol.models import model_endpoint
from roami_agent.providers.model_catalog import fetch_catalog
from roami_agent.providers.reasoning_effort import reasoning_efforts, with_reasoning_effort

KEY_NAMES = {"main": "ROAMI_AGENT_SAVED_MAIN_KEY", "worker": "ROAMI_AGENT_SAVED_WORKER_KEY"}


class RuntimeSettings:
    def __init__(self, current):
        self.current = current
        self.updating = False

    def __getattr__(self, name):
        value = getattr(self.current, name)
        if name in {
            "memory_recall_limit",
            "memory_recall_tokens",
            "tool_directory_page_size",
            "keep_recent_tokens",
        }:
            return policy_value(name, value)
        return value


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
        if not isinstance(saved, dict) or set(saved) - {"main", "worker", "connection", "proxy"}:
            raise ValueError
        return saved
    except (ValueError, OSError):
        raise DomainError("MODEL_SETTINGS_INVALID", 503) from None


def effective_settings(base, saved, *, credentials=True):
    connection = saved.get("connection")
    if connection is not None and (
        not isinstance(connection, dict)
        or set(connection) - {"baseUrl", "apiKey"}
        or any(not isinstance(value, str) for value in connection.values())
    ):
        raise DomainError("INVALID_MODEL_CONFIG")
    routes = {}
    for role in ("main", "worker"):
        old = base.route(role)
        value = saved.get(role, {})
        if not isinstance(value, dict) or set(value) - {
            "baseUrl",
            "model",
            "apiKey",
            "images",
            "contextWindow",
            "reasoningEffort",
        }:
            raise DomainError("INVALID_MODEL_CONFIG")
        if any(
            key in value and not isinstance(value[key], str)
            for key in ("baseUrl", "model", "apiKey")
        ):
            raise DomainError("INVALID_MODEL_CONFIG")
        endpoint = model_endpoint(
            (
                connection.get("baseUrl", base.route("main").endpoint)
                if connection is not None
                else value.get("baseUrl", old.endpoint)
            ).strip()
        )
        name = value.get("model", old.name).strip()
        key_value = connection.get("apiKey") if connection is not None else value.get("apiKey")
        key_env = (
            KEY_NAMES["main" if connection is not None else role]
            if key_value
            else base.route("main").key_env
            if connection is not None
            else old.key_env
        )
        if credentials and key_value:
            os.environ[key_env] = key_value
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
        window = value.get(
            "contextWindow",
            old.context_window if (endpoint, name) == (old.endpoint, old.name) else None,
        )
        if window is not None and (type(window) is not int or not 1 <= window <= 100_000_000):
            raise DomainError("INVALID_MODEL_CONFIG")
        routes[role] = ModelRoute(
            endpoint,
            name,
            key_env,
            old.timeout_seconds,
            old.max_retries,
            capabilities,
            old.cache,
            with_reasoning_effort(old.parameters, name, value["reasoningEffort"])
            if "reasoningEffort" in value
            else old.parameters,
            window,
            old.image_limits if (endpoint, name) == (old.endpoint, old.name) else {},
        )
    main, worker = routes["main"], routes["worker"]
    return replace(
        base,
        endpoint=main.endpoint,
        model=main.name,
        key_env=main.key_env,
        model_capabilities=main.capabilities,
        context_window=main.context_window,
        image_limits=main.image_limits,
        model_parameters=main.parameters,
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
        result = {
            role: {
                "baseUrl": self.runtime.settings.route(role).endpoint,
                "model": self.runtime.settings.route(role).name,
                "keyConfigured": bool(self.runtime.settings.credentials(role)),
                "images": self.runtime.settings.route(role).capabilities.get("images") is True,
                "contextWindow": self.runtime.settings.route(role).context_window,
                "configuredContextWindow": self.saved.get(role, {}).get("contextWindow"),
                "reasoningEffort": self.runtime.settings.route(role).parameters.get(
                    "reasoning_effort"
                ),
                "reasoningEfforts": reasoning_efforts(self.runtime.settings.route(role).name),
            }
            for role in ("main", "worker")
        }
        result["connection"] = {
            "baseUrl": result["main"]["baseUrl"],
            "keyConfigured": result["main"]["keyConfigured"],
        }
        result["gatewayManaged"] = True
        return result

    def merge(self, patch):
        if (
            not isinstance(patch, dict)
            or not patch
            or set(patch) - {"main", "worker", "connection"}
        ):
            raise DomainError("INVALID_MODEL_CONFIG")
        saved = deepcopy(self.saved)
        if "connection" in patch:
            changes = patch["connection"]
            if not isinstance(changes, dict) or set(changes) - {"baseUrl", "apiKey"}:
                raise DomainError("INVALID_MODEL_CONFIG")
            connection = saved.setdefault(
                "connection", {"baseUrl": self.runtime.settings.route("main").endpoint}
            )
            if not connection.get("apiKey") and saved.get("main", {}).get("apiKey"):
                connection["apiKey"] = saved["main"]["apiKey"]
            for name, value in changes.items():
                if (
                    not isinstance(value, str)
                    or len(value) > (4096 if name == "apiKey" else 2000)
                    or any(ord(c) < 32 for c in value)
                ):
                    raise DomainError("INVALID_MODEL_CONFIG")
                if name == "apiKey" and not value.strip():
                    continue
                connection[name] = value.strip()
            for role in ("main", "worker"):
                item = saved.setdefault(role, {})
                item.pop("apiKey", None)
                item.pop("baseUrl", None)
                if connection["baseUrl"].rstrip("/") != self.runtime.settings.route(
                    role
                ).endpoint.rstrip("/"):
                    item["contextWindow"] = None
                    item["reasoningEffort"] = None
        for role, changes in patch.items():
            if role in {"connection", "proxy"}:
                continue
            if (
                "connection" in saved
                and isinstance(changes, dict)
                and set(changes) & {"baseUrl", "apiKey"}
            ):
                raise DomainError("INVALID_MODEL_CONFIG")
            if not isinstance(changes, dict) or set(changes) - {
                "baseUrl",
                "model",
                "apiKey",
                "images",
                "contextWindow",
                "reasoningEffort",
            }:
                raise DomainError("INVALID_MODEL_CONFIG")
            item = saved.setdefault(role, {})
            current = self.runtime.settings.route(role)
            model_changed = (
                isinstance(changes.get("model"), str) and changes["model"].strip() != current.name
            )
            endpoint_changed = isinstance(changes.get("baseUrl"), str) and changes[
                "baseUrl"
            ].strip().rstrip("/") != current.endpoint.rstrip("/")
            if model_changed or endpoint_changed:
                item["contextWindow"] = None
                item["reasoningEffort"] = None
            for key, value in changes.items():
                if key == "reasoningEffort":
                    with_reasoning_effort({}, changes.get("model", current.name), value)
                elif key == "contextWindow":
                    if value is not None and (
                        type(value) is not int or not 1 <= value <= 100_000_000
                    ):
                        raise DomainError("INVALID_MODEL_CONFIG")
                elif key == "images":
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
                if role == "proxy":
                    continue
                route = self.runtime.settings.route("main" if role == "connection" else role)
                if (
                    change.get("baseUrl", route.endpoint).rstrip("/") != route.endpoint
                    and self.runtime.settings.credentials("main" if role == "connection" else role)
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
                settings = await self.resolve_capacity(effective_settings(self.base, saved))
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
                    VisionInputs(runtime.db, runtime.artifacts, runtime.settings)
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
        route = self.runtime.settings.route("main" if patch and "connection" in patch else role)
        supplied = (patch or {}).get("connection", (patch or {}).get(role, {}))
        if patch:
            self.merge(patch)
            candidate = replace(
                route, endpoint=model_endpoint(supplied.get("baseUrl", route.endpoint).strip())
            )
            if (
                candidate.endpoint != route.endpoint
                and self.runtime.settings.credentials(
                    "main" if patch and "connection" in patch else role
                )
                and not supplied.get("apiKey")
            ):
                raise DomainError("MODEL_KEY_REQUIRED_FOR_ENDPOINT")
            route = candidate
        if not route.endpoint:
            raise DomainError("MODEL_NOT_CONFIGURED", 503)
        key = supplied.get("apiKey") or self.runtime.settings.credentials(
            "main" if patch and "connection" in patch else role
        )
        catalog = await fetch_catalog(route.endpoint, key)
        names = sorted(catalog)
        return {
            "models": names[:200],
            "truncated": len(names) > 200,
            "contextWindows": {name: catalog[name] for name in names[:200] if catalog[name]},
            "reasoningEfforts": {name: reasoning_efforts(name) for name in names[:200]},
        }

    async def resolve_capacity(self, settings):
        async def resolve(role):
            route = settings.route(role)
            if route.context_window is not None or not route.endpoint or not route.name:
                return route
            try:
                catalog = await fetch_catalog(route.endpoint, settings.credentials(role))
            except DomainError:
                return route
            return replace(route, context_window=catalog.get(route.name))

        main, worker = await asyncio.gather(resolve("main"), resolve("worker"))
        return replace(settings, context_window=main.context_window, worker_route=worker)

    async def refresh_capacity(self):
        self.runtime.settings.current = await self.resolve_capacity(self.runtime.settings.current)

    async def close(self):
        for provider in self.owned_providers:
            await provider.close()
