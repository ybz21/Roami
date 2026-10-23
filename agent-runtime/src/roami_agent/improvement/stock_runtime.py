"""Case-scoped stock file transport sharing write reconciliation and audit records."""

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

from roami_agent.improvement.company_runtime import CompanyRuntime
from roami_agent.improvement.contracts import relative_file, require
from roami_agent.improvement.executors import private_json
from roami_agent.improvement.stock_environment import (
    FOLDER,
    MAX_FILE,
    OUTPUTS,
    SOURCE,
    StockEnvironment,
)


class StockRuntime(CompanyRuntime):
    def normalize(self, method, path, body):
        require(isinstance(path, str), "RSI_COMPANY_ROUTE")
        outputs = {FOLDER + "/" + name for name in OUTPUTS}
        if method == "GET":
            require(path in outputs | {SOURCE} and body is None, "RSI_COMPANY_ROUTE")
        elif method == "MKCOL":
            require(path == FOLDER and body is None, "RSI_COMPANY_ROUTE")
        elif method == "PUT":
            require(
                path in outputs and isinstance(body, dict) and set(body) == {"file"},
                "RSI_COMPANY_ROUTE",
            )
            require(isinstance(body["file"], str), "RSI_COMPANY_ARGUMENTS")
            file = relative_file(self.environment.workspace, body["file"])
            require(file.is_file() and file.stat().st_size <= MAX_FILE, "RSI_COMPANY_ARGUMENTS")
            body = {**body, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
        else:
            require(False, "RSI_COMPANY_ROUTE")
        return path, body


CLIENT = r"""import base64,json,pathlib,socket,sys
if len(sys.argv) not in (3,4):raise SystemExit('Usage: python stock-http.py GET|MKCOL|PUT /Documents/path [local-file]')
method,path=sys.argv[1:3];body=None
if method=='PUT':body={'file':str(pathlib.Path(sys.argv[3]).relative_to('/workspace')) if sys.argv[3].startswith('/') else sys.argv[3]}
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
 s.settimeout(30);s.connect('/model/company.sock');s.sendall(json.dumps({'method':method,'path':path,'body':body}).encode()+b'\n');s.shutdown(socket.SHUT_WR);chunks=[]
 while data:=s.recv(65536):chunks.append(data)
 result=json.loads(b''.join(chunks))
 if method=='GET' and result.get('status')==200:
  if len(sys.argv)!=4:raise SystemExit('GET needs a local destination file')
  raw=base64.b64decode(result['body'].pop('content_base64'),validate=True);pathlib.Path(sys.argv[3]).write_bytes(raw);result['body']['saved_bytes']=len(raw)
 print(json.dumps(result));raise SystemExit(0 if result.get('status',500)<400 else 1)
"""


@asynccontextmanager
async def stock_runtime(case, directory, workspace, root, deadline):
    environment = StockEnvironment(case["judge"], deadline, workspace, root)
    runtime = StockRuntime(Path(directory) / "company.sock", environment, deadline)
    try:
        await environment.start()
        with (workspace / "stock-http.py").open("x") as stream:
            stream.write(CLIENT)
        async with runtime:
            yield runtime
        await environment.snapshot(persist=True)
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
