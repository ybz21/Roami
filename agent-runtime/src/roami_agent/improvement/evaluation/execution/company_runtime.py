"""Allowlisted case-local RocketChat API bridge; no service tokens enter the agent."""

import asyncio
import json
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from roami_agent.improvement.domain.contracts import digest, require
from roami_agent.improvement.evaluation.execution.company_environment import (
    PROFILE_FIELDS,
    CompanyEnvironment,
)
from roami_agent.improvement.integrations.artifact_files import private_json
from roami_agent.protocol.errors import DomainError

GET_ROUTES = {"/api/v1/users.list", "/api/v1/users.info", "/api/v1/im.list", "/api/v1/im.history"}
POST_ROUTES = {"/api/v1/im.create", "/api/v1/chat.postMessage"}


def native_request(method, path, body):
    require(
        method in {"GET", "POST"} and isinstance(path, str) and len(path) <= 4000,
        "RSI_COMPANY_ROUTE",
    )
    parsed = urlsplit(path)
    require(not parsed.scheme and not parsed.netloc and not parsed.fragment, "RSI_COMPANY_ROUTE")
    require("\r" not in path and "\n" not in path and "\\" not in path, "RSI_COMPANY_ROUTE")
    if method == "POST":
        require(parsed.path in POST_ROUTES and not parsed.query, "RSI_COMPANY_ROUTE")
        require(isinstance(body, dict), "RSI_COMPANY_ARGUMENTS")
        if parsed.path.endswith("im.create"):
            require(
                set(body) == {"username"}
                and isinstance(body["username"], str)
                and re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", body["username"]),
                "RSI_COMPANY_ARGUMENTS",
            )
        else:
            require(set(body) == {"roomId", "text"}, "RSI_COMPANY_ARGUMENTS")
            require(
                isinstance(body["roomId"], str)
                and re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", body["roomId"]),
                "RSI_COMPANY_ARGUMENTS",
            )
            require(
                isinstance(body["text"], str)
                and 1 <= len(body["text"]) <= 4000
                and not re.search(r"https?://", body["text"], re.IGNORECASE),
                "RSI_COMPANY_ARGUMENTS",
            )
        return parsed.path, body
    require(parsed.path in GET_ROUTES and body is None, "RSI_COMPANY_ROUTE")
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    require(all(len(v) == 1 for v in query.values()), "RSI_COMPANY_ARGUMENTS")
    allowed = {
        "/api/v1/users.list": {"offset", "count", "query", "fields"},
        "/api/v1/users.info": {"username", "userId", "fields"},
        "/api/v1/im.list": {"offset", "count"},
        "/api/v1/im.history": {"roomId", "offset", "count"},
    }[parsed.path]
    require(set(query) <= allowed, "RSI_COMPANY_ARGUMENTS")
    clean = {key: values[0] for key, values in query.items()}
    for key in ("offset", "count"):
        if key in clean:
            require(bool(re.fullmatch(r"\d{1,5}", clean[key])), "RSI_COMPANY_ARGUMENTS")
            require(
                0 <= int(clean[key]) <= (100 if key == "count" else 10000), "RSI_COMPANY_ARGUMENTS"
            )
    for key in ("username", "userId", "roomId"):
        if key in clean:
            require(
                bool(re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", clean[key])), "RSI_COMPANY_ARGUMENTS"
            )
    if "query" in clean:
        selection = json.loads(clean["query"])
        require(
            isinstance(selection, dict) and set(selection) <= {"name", "username"},
            "RSI_COMPANY_ARGUMENTS",
        )
        for value in selection.values():
            require(isinstance(value, str) and 1 <= len(value) <= 100, "RSI_COMPANY_ARGUMENTS")
    if parsed.path.startswith("/api/v1/users."):
        clean["fields"] = json.dumps(PROFILE_FIELDS)
    return parsed.path + ("?" + urlencode(clean) if clean else ""), None


class CompanyRuntime:
    normalize = staticmethod(native_request)

    def __init__(self, socket, environment, deadline):
        self.socket, self.environment, self.deadline = socket, environment, deadline
        self.records, self.clients = [], set()
        self.lock = asyncio.Lock()
        self.completed_writes = {}
        self.unknown_write = False

    async def __aenter__(self):
        self.server = await asyncio.start_unix_server(
            self.handle, path=str(self.socket), limit=64001
        )
        return self

    async def __aexit__(self, *error):
        self.server.close()
        await self.server.wait_closed()
        clients = list(self.clients)
        for task in clients:
            task.cancel()
        await asyncio.gather(*clients, return_exceptions=True)

    async def execute(self, method, path, body=None):
        native_path, body = self.normalize(method, path, body)
        async with self.lock:
            require(len(self.records) < 64, "RSI_COMPANY_REQUEST_LIMIT")
            require(time.monotonic() < self.deadline, "RSI_TIME_BUDGET")
            require(not (method != "GET" and self.unknown_write), "RSI_COMPANY_WRITE_UNKNOWN")
            record = {
                "id": "company-" + str(len(self.records) + 1),
                "state": "running",
                "tool_name": "company_http",
                "arguments_json": json.dumps({"method": method, "path": native_path, "body": body}),
            }
            self.records.append(record)
            started = time.monotonic()
            key = digest([method, native_path, body])
            try:
                if method != "GET" and key in self.completed_writes:
                    result = {**self.completed_writes[key], "cached": True}
                else:
                    result = await self.environment.request(method, native_path, body)
                    if native_path.startswith("/api/v1/users."):
                        payload = dict(result["body"])
                        for field in ("users", "user"):
                            if field in payload:
                                values = payload[field] if field == "users" else [payload[field]]
                                clean = [
                                    {k: v for k, v in user.items() if k in {*PROFILE_FIELDS, "_id"}}
                                    for user in values
                                ]
                                payload[field] = clean if field == "users" else clean[0]
                        result = {**result, "body": payload}
                    if (
                        method != "GET"
                        and result["status"] < 400
                        and result["body"].get("success") is not False
                    ):
                        self.completed_writes[key] = result
                record.update(
                    state="succeeded"
                    if result["status"] < 400 and result["body"].get("success") is not False
                    else "failed",
                    result_json=json.dumps(result, ensure_ascii=False),
                )
                if method != "GET" and (result["status"] == 408 or result["status"] >= 500):
                    self.unknown_write = True
                    record["state"] = "unknown"
                return result
            except asyncio.CancelledError:
                record.update(
                    state="unknown", result_json=json.dumps({"error": "RSI_COMPANY_INTERRUPTED"})
                )
                self.unknown_write |= method != "GET"
                raise
            except (DomainError, OSError, ValueError, TypeError, TimeoutError) as error:
                self.unknown_write |= method != "GET"
                record.update(
                    state="unknown" if method != "GET" else "failed",
                    result_json=json.dumps(
                        {
                            "error": error.code
                            if isinstance(error, DomainError)
                            else "RSI_COMPANY_REQUEST_FAILED"
                        }
                    ),
                )
                raise
            finally:
                record["elapsed_ms"] = (time.monotonic() - started) * 1000

    async def handle(self, reader, writer):
        self.clients.add(asyncio.current_task())
        try:
            try:
                async with asyncio.timeout(10):
                    raw = await reader.readline()
                    require(len(raw) <= 64000, "RSI_COMPANY_ARGUMENTS")
                    data = json.loads(raw)
                result = await self.execute(data["method"], data["path"], data.get("body"))
            except (DomainError, OSError, ValueError, KeyError, TypeError, TimeoutError) as error:
                result = {
                    "status": 400,
                    "error": error.code
                    if isinstance(error, DomainError)
                    else "RSI_COMPANY_REQUEST_FAILED",
                }
            writer.write(json.dumps(result).encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            self.clients.discard(asyncio.current_task())


CLIENT = r"""import json,socket,sys
if not 3<=len(sys.argv)<=4:raise SystemExit('Usage: python company-http.py GET|POST /api/v1/path [JSON]')
payload={'method':sys.argv[1],'path':sys.argv[2],'body':json.loads(sys.argv[3]) if len(sys.argv)==4 else None}
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
 s.settimeout(30);s.connect('/model/company.sock');s.sendall(json.dumps(payload).encode()+b'\n');s.shutdown(socket.SHUT_WR)
 chunks=[]
 while data:=s.recv(65536):chunks.append(data)
 result=json.loads(b''.join(chunks));print(json.dumps(result,ensure_ascii=False))
 raise SystemExit(0 if result.get('status',500)<400 else 1)
"""


@asynccontextmanager
async def company_runtime(case, directory, workspace, root, deadline):
    if case["judge"]["kind"] == "company_stock":
        from roami_agent.improvement.evaluation.execution.stock_runtime import stock_runtime

        async with stock_runtime(case, directory, workspace, root, deadline) as runtime:
            yield runtime
        return
    if case["judge"]["kind"] != "company":
        yield None
        return
    environment = CompanyEnvironment(case["judge"], deadline)
    runtime = CompanyRuntime(Path(directory) / "company.sock", environment, deadline)
    try:
        await environment.start()
        with (workspace / "company-http.py").open("x") as stream:
            stream.write(CLIENT)
        async with runtime:
            yield runtime
        snapshot = await environment.snapshot()
        private_json(
            root / "company-snapshot.json",
            {
                "initial": environment.initial,
                "final": snapshot,
                "image_ids": environment.image_ids,
                "scope": environment.scope,
            },
        )
    finally:
        try:
            await environment.close()
        finally:
            private_json(
                root / "company-runtime-log.json",
                {
                    "tool_calls": runtime.records,
                    "traces": [],
                    "native_http_calls": environment.http_calls,
                    "network": "internal_unpublished",
                    "provider_keys_in_services": False,
                },
            )
