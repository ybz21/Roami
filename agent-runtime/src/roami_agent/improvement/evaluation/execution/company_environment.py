"""Per-trial RocketChat and MongoDB, restored from a pinned benchmark snapshot."""

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

from roami_agent.improvement.domain.contracts import require
from roami_agent.protocol.errors import DomainError

IMAGE_RE = {
    "mongo": r"mongo@sha256:[a-f0-9]{64}",
    "rocketchat": r"rocketchat/rocket\.chat@sha256:[a-f0-9]{64}",
}
PROFILE_FIELDS = {key: 1 for key in ("name", "username", "nameInsensitive", "bio", "customFields")}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


async def resolve_images(images):
    from roami_agent.improvement.evaluation.execution.containers import docker_command

    require(isinstance(images, dict) and set(images) == set(IMAGE_RE))
    result = {}
    for role, reference in images.items():
        require(isinstance(reference, str) and re.fullmatch(IMAGE_RE[role], reference))
        data = json.loads(await docker_command("image", "inspect", reference))[0]
        require(reference in data.get("RepoDigests", []), "RSI_COMPANY_IMAGE_REQUIRED")
        result[role] = data["Id"]
    return result


class CompanyEnvironment:
    def __init__(self, spec, deadline):
        self.spec, self.deadline = spec, deadline
        self.scope = "roami-rsi-company-" + secrets.token_hex(8)
        self.network = self.scope + "-net"
        self.containers = []
        self.network_created = False
        self.base = None
        self.auth = {}
        self.ready = False
        self.initial = None
        self.http_calls = 0

    async def command(self, *args, input=None, timeout=30):
        from roami_agent.improvement.evaluation.execution.containers import docker_command

        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "RSI_TIME_BUDGET")
        return await docker_command(*args, input=input, timeout=min(timeout, remaining))

    def http(self, method, path, body=None, *, authenticated=True):
        require(
            self.base is not None and path.startswith("/") and "\r" not in path and "\n" not in path
        )
        require("#" not in path and not path.startswith("//"), "RSI_COMPANY_ROUTE")
        headers = {"Content-Type": "application/json", **(self.auth if authenticated else {})}
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.http_calls += 1
        try:
            with client.open(
                request, timeout=max(0.01, min(10, self.deadline - time.monotonic()))
            ) as response:
                raw = response.read(1_000_001)
                require(len(raw) <= 1_000_000, "RSI_COMPANY_RESPONSE_LIMIT")
                return {"status": response.status, "body": json.loads(raw)}
        except urllib.error.HTTPError as error:
            raw = error.read(16000)
            try:
                body = json.loads(raw)
            except ValueError:
                body = {"error": "native_http_error"}
            return {"status": error.code, "body": body}

    async def request(self, method, path, body=None, *, authenticated=True):
        require(time.monotonic() < self.deadline, "RSI_TIME_BUDGET")
        return await asyncio.to_thread(self.http, method, path, body, authenticated=authenticated)

    async def start(self):
        images = await resolve_images(self.spec["images"])
        self.image_ids = images
        dump = base64.b64decode(self.spec["db_dump"], validate=True)
        require(hashlib.sha256(dump).hexdigest() == self.spec["db_sha256"], "RSI_SOURCE_CHANGED")
        await self.command(
            "network", "create", "--internal", "--label", "roami.rsi=" + self.scope, self.network
        )
        self.network_created = True
        mongo, rocket = self.scope + "-mongo", self.scope + "-rocket"
        hardening = [
            "--label",
            "roami.rsi=" + self.scope,
            "--network",
            self.network,
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "256",
        ]
        await self.command(
            "create",
            "--name",
            mongo,
            *hardening,
            "--network-alias",
            "mongodb",
            "--memory",
            "1g",
            "--cpus",
            "1",
            "--tmpfs",
            "/data/db:rw,exec,size=805306368,mode=1777",
            "--tmpfs",
            "/tmp:rw,size=134217728,mode=1777",
            images["mongo"],
            "--replSet",
            "rs0",
            "--bind_ip_all",
            "--wiredTigerCacheSizeGB",
            "0.25",
        )
        self.containers.append(mongo)
        await self.command("start", mongo)
        for _ in range(60):
            try:
                await self.command(
                    "exec",
                    mongo,
                    "mongo",
                    "--quiet",
                    "--eval",
                    "db.adminCommand({ping:1})",
                    timeout=5,
                )
                break
            except (DomainError, OSError, TimeoutError):
                await asyncio.sleep(1)
        else:
            raise DomainError("RSI_COMPANY_DATABASE_UNAVAILABLE")
        await self.command(
            "exec",
            mongo,
            "mongo",
            "--quiet",
            "--eval",
            "rs.initiate({_id:'rs0',members:[{_id:0,host:'mongodb:27017'}]})",
        )
        for _ in range(60):
            raw = await self.command(
                "exec", mongo, "mongo", "--quiet", "--eval", "print(db.isMaster().ismaster)"
            )
            if "true" in raw.decode():
                break
            await asyncio.sleep(1)
        else:
            raise DomainError("RSI_COMPANY_DATABASE_UNAVAILABLE")
        await self.command(
            "exec", "-i", mongo, "mongorestore", "--archive", "--drop", input=dump, timeout=90
        )
        env = {
            "MONGO_URL": "mongodb://mongodb:27017/rocketchat?replicaSet=rs0",
            "MONGO_OPLOG_URL": "mongodb://mongodb:27017/local?replicaSet=rs0",
            "ROOT_URL": "http://the-agent-company.com:3000",
            "PORT": "3000",
            "DEPLOY_METHOD": "docker",
            "Show_Setup_Wizard": "completed",
            "OVERWRITE_SETTING_Show_Setup_Wizard": "completed",
            "ADMIN_USERNAME": "theagentcompany",
            "ADMIN_PASS": "theagentcompany",
            "ADMIN_EMAIL": "theagentcompany@example.com",
            "ADMIN_NAME": "theagentcompany",
            "HOME": "/tmp/home",
            "OVERWRITE_SETTING_Statistics_enabled": "false",
            "OVERWRITE_SETTING_URLPreviewEnabled": "false",
        }
        await self.command(
            "create",
            "--name",
            rocket,
            *hardening,
            "--memory",
            "1500m",
            "--cpus",
            "2",
            "--tmpfs",
            "/tmp:rw,exec,size=268435456,mode=1777",
            "--tmpfs",
            "/app/uploads:rw,size=134217728,mode=1777",
            *(arg for key, value in env.items() for arg in ("-e", key + "=" + value)),
            images["rocketchat"],
        )
        self.containers.append(rocket)
        await self.command("start", rocket)
        info = json.loads(await self.command("inspect", rocket))[0]
        address = info["NetworkSettings"]["Networks"][self.network]["IPAddress"]
        require(bool(re.fullmatch(r"\d+\.\d+\.\d+\.\d+", address)), "RSI_COMPANY_ADDRESS")
        self.base = "http://" + address + ":3000"
        cutoff = min(self.deadline, time.monotonic() + 240)
        while time.monotonic() < cutoff:
            try:
                response = await self.request("GET", "/api/info", authenticated=False)
                if response["status"] == 200:
                    break
            except (DomainError, OSError, ValueError, TimeoutError):
                pass
            await asyncio.sleep(2)
        else:
            raise DomainError("RSI_COMPANY_APPLICATION_UNAVAILABLE")
        login = await self.request(
            "POST",
            "/api/v1/login",
            {"user": "theagentcompany", "password": "theagentcompany"},
            authenticated=False,
        )
        require(
            login["status"] == 200 and login["body"].get("status") == "success",
            "RSI_COMPANY_AUTHENTICATION",
        )
        data = login["body"]["data"]
        self.auth = {"X-User-Id": data["userId"], "X-Auth-Token": data["authToken"]}
        self.ready = True
        self.initial = await self.snapshot()

    async def snapshot(self):
        profiles = await self.request(
            "GET",
            "/api/v1/users.list?" + urlencode({"count": 100, "fields": json.dumps(PROFILE_FIELDS)}),
        )
        rooms = await self.request("GET", "/api/v1/im.list?count=100")
        require(profiles["status"] == rooms["status"] == 200, "RSI_COMPANY_SNAPSHOT_FAILED")
        users = profiles["body"].get("users")
        direct = rooms["body"].get("ims")
        require(isinstance(users, list) and isinstance(direct, list), "RSI_COMPANY_SNAPSHOT_FAILED")
        require(profiles["body"].get("total", len(users)) <= 100, "RSI_COMPANY_RESPONSE_LIMIT")
        histories = {}
        for room in direct:
            response = await self.request(
                "GET", "/api/v1/im.history?" + urlencode({"roomId": room["_id"], "count": 100})
            )
            require(
                response["status"] == 200 and isinstance(response["body"].get("messages"), list),
                "RSI_COMPANY_SNAPSHOT_FAILED",
            )
            histories[room["_id"]] = response["body"]["messages"]
        return {
            "users": users,
            "rooms": direct,
            "messages": histories,
            "actor_id": self.auth["X-User-Id"],
        }

    async def close(self):
        from roami_agent.improvement.evaluation.execution.containers import (
            docker_command,
            remove_container,
        )

        errors = []
        for name in reversed(self.containers):
            try:
                await remove_container(name, self.scope)
            except (DomainError, OSError, TimeoutError) as error:
                errors.append(error)
        if self.network_created:
            try:
                info = json.loads(await docker_command("network", "inspect", self.network))[0]
                require(
                    info["Labels"].get("roami.rsi") == self.scope, "RSI_CONTAINER_IDENTITY_CHANGED"
                )
                await docker_command("network", "rm", self.network)
            except (DomainError, OSError, TimeoutError) as error:
                errors.append(error)
        self.auth.clear()
        if errors:
            raise errors[0]
