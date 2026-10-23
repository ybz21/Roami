"""Fresh native benchmark ownCloud and a restricted binary WebDAV transport."""

import asyncio
import base64
import hashlib
import json
import re
import time
import urllib.error
import urllib.request

from roami_agent.improvement.company_environment import CompanyEnvironment, NoRedirect
from roami_agent.improvement.contracts import relative_file, require
from roami_agent.improvement.executors import private_json
from roami_agent.protocol.errors import DomainError

IMAGE_RE = r"ghcr\.io/theagentcompany/servers-owncloud@sha256:[a-f0-9]{64}"
SOURCE = "/Documents/Financials/stock_data_raw.csv"
FOLDER = "/Documents/Financials/stock_presentation"
OUTPUTS = ("stock_cleaned.csv", "stock_analysis.pptx", "stock_analysis_script.md")
MAX_FILE = 8_000_000


async def resolve_image(reference):
    from roami_agent.improvement.containers import docker_command

    require(isinstance(reference, str) and re.fullmatch(IMAGE_RE, reference))
    info = json.loads(await docker_command("image", "inspect", reference))[0]
    require(reference in info.get("RepoDigests", []), "RSI_COMPANY_IMAGE_REQUIRED")
    return info["Id"]


class StockEnvironment(CompanyEnvironment):
    def __init__(self, spec, deadline, workspace, root):
        super().__init__(spec, deadline)
        self.workspace, self.root = workspace, root

    def http(self, method, path, body=None, **kwargs):
        data = None
        if method == "PUT":
            file = relative_file(self.workspace, body["file"])
            require(file.is_file() and file.stat().st_size <= MAX_FILE)
            data = file.read_bytes()
            require(hashlib.sha256(data).hexdigest() == body["sha256"], "RSI_SOURCE_CHANGED")
        headers = {
            "Authorization": "Basic "
            + base64.b64encode(b"theagentcompany:theagentcompany").decode(),
            "Host": "localhost:8091",
            "Content-Type": "application/octet-stream",
        }
        request = urllib.request.Request(
            self.base + "/remote.php/webdav" + path, data=data, headers=headers, method=method
        )
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.http_calls += 1
        try:
            with client.open(
                request, timeout=max(0.01, min(15, self.deadline - time.monotonic()))
            ) as response:
                raw = response.read(MAX_FILE + 1)
                require(len(raw) <= MAX_FILE, "RSI_COMPANY_RESPONSE_LIMIT")
                return {
                    "status": response.status,
                    "body": {
                        "content_base64": base64.b64encode(raw).decode() if method == "GET" else "",
                        "sha256": hashlib.sha256(raw).hexdigest() if method == "GET" else None,
                    },
                }
        except urllib.error.HTTPError as error:
            return {"status": error.code, "body": {"error": "native_webdav_error"}}

    async def start(self):
        image = await resolve_image(self.spec["image"])
        self.image_ids = {"owncloud": image}
        await self.command(
            "network", "create", "--internal", "--label", "roami.rsi=" + self.scope, self.network
        )
        self.network_created = True
        name = self.scope + "-owncloud"
        await self.command(
            "create",
            "--name",
            name,
            "--label",
            "roami.rsi=" + self.scope,
            "--network",
            self.network,
            "--user",
            "33:33",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "128",
            "--memory",
            "1g",
            "--cpus",
            "2",
            "--tmpfs",
            "/tmp:rw,size=134217728,mode=1777",
            "--tmpfs",
            "/var/run/apache2:rw,size=16777216,uid=33,gid=33",
            "--tmpfs",
            "/var/lock/apache2:rw,size=16777216,uid=33,gid=33",
            "--tmpfs",
            "/var/log/apache2:rw,size=33554432,uid=33,gid=33",
            "--entrypoint",
            "apache2-foreground",
            image,
        )
        self.containers.append(name)
        await self.command("start", name)
        info = json.loads(await self.command("inspect", name))[0]
        address = info["NetworkSettings"]["Networks"][self.network]["IPAddress"]
        require(bool(re.fullmatch(r"\d+\.\d+\.\d+\.\d+", address)))
        self.base = "http://" + address
        for _ in range(30):
            try:
                response = await self.request("GET", SOURCE)
                if response["status"] == 200:
                    break
            except (DomainError, OSError, ValueError, TimeoutError):
                pass
            await asyncio.sleep(2)
        else:
            raise DomainError("RSI_COMPANY_APPLICATION_UNAVAILABLE")
        self.initial = await self.snapshot()
        require(self.initial["source_sha256"] == self.spec["raw_sha256"], "RSI_SOURCE_CHANGED")
        require(not self.initial["outputs"], "RSI_COMPANY_DIRTY_BASELINE")

    async def snapshot(self, *, persist=False):
        source = await self.request("GET", SOURCE)
        require(source["status"] == 200, "RSI_COMPANY_SNAPSHOT_FAILED")
        outputs = {}
        remote = self.root / "stock-remote"
        if persist:
            remote.mkdir(mode=0o700)
        for name in OUTPUTS:
            result = await self.request("GET", FOLDER + "/" + name)
            if result["status"] == 404:
                continue
            require(result["status"] == 200, "RSI_COMPANY_SNAPSHOT_FAILED")
            data = base64.b64decode(result["body"]["content_base64"], validate=True)
            outputs[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            if persist:
                file = remote / name
                file.write_bytes(data)
                file.chmod(0o600)
        state = {"source_sha256": source["body"]["sha256"], "outputs": outputs}
        if persist:
            private_json(
                self.root / "stock-snapshot.json", {"initial": self.initial, "final": state}
            )
        return state

    async def close(self):
        from roami_agent.improvement.containers import docker_command

        errors = []
        for name in reversed(self.containers):
            try:
                info = json.loads(await docker_command("inspect", name))[0]
                require(
                    info["Config"]["Labels"].get("roami.rsi") == self.scope,
                    "RSI_CONTAINER_IDENTITY_CHANGED",
                )
                require(
                    all(
                        m["Type"] == "volume"
                        for m in info["Mounts"]
                        if m["Destination"] == "/var/www/html"
                    )
                )
                await docker_command("rm", "--force", "--volumes", name)
            except (DomainError, OSError, TimeoutError) as error:
                errors.append(error)
        self.containers.clear()
        try:
            await super().close()
        except (DomainError, OSError, TimeoutError) as error:
            errors.append(error)
        if errors:
            raise errors[0]
