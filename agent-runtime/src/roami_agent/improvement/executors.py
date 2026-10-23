"""File-only runtime evaluation and an explicit external benchmark worker protocol."""

import asyncio
import base64
import json
import os
import signal
import time
from dataclasses import replace
from pathlib import Path

from roami_agent.app import Runtime, configured_provider
from roami_agent.improvement.contracts import agent_view, digest, load_json, relative_file, require
from roami_agent.improvement.grading import judge_case, validate_external_grade
from roami_agent.improvement.measurements import EpisodeBudget, MeteredModel, trace_metrics
from roami_agent.improvement.policy import apply_policy
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.model_routes import settings_with_route
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import Database, row


def private_json(path, value):
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def materialize(case, workspace):
    workspace.mkdir(mode=0o700)
    for name, content in case.get("files", {}).items():
        path = relative_file(workspace, name)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(content)
    for name, content in case.get("asset_files", {}).items():
        path = relative_file(workspace, name)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = base64.b64decode(content, validate=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)


class ProtocolFixtureModel:
    """Exercises real intake/tools/persistence, never estimates model capability."""

    model = "rsi-protocol-fixture"

    def __init__(self, script=None):
        self.script = script or [{"text": '{"memories":[]}'}]
        self.index = 0

    async def stream(self, messages, tools):
        step = self.script[min(self.index, len(self.script) - 1)]
        self.index += 1
        if "tool" in step:
            call = step["tool"]
            yield ModelEvent(
                "tool",
                {
                    "id": "fixture-" + str(self.index),
                    "type": "function",
                    "function": {"name": call["name"], "arguments": json.dumps(call["args"])},
                },
            )
        else:
            yield ModelEvent("text", step["text"])
        yield ModelEvent(
            "usage",
            {"inputTokens": 100, "outputTokens": 20, "requestAttempts": 1, "retryUsageKnown": True},
        )


class NativeFilesExecutor:
    def __init__(
        self,
        settings,
        *,
        fixture=False,
        settle_maintenance=False,
        allow_shell=False,
        workspace=None,
        provider_factory=None,
    ):
        self.settings, self.fixture = settings, fixture
        self.settle_maintenance = settle_maintenance
        self.allow_shell, self.workspace = allow_shell, workspace
        self.provider_factory = provider_factory
        require(
            not allow_shell
            or (Path("/.dockerenv").exists() and os.environ.get("ROAMI_RSI_CONTAINER") == "1"),
            "RSI_CONTAINER_REQUIRED",
        )
        routes = [settings.route(role) for role in ("main", "worker")]
        self.model_hash = digest(
            [
                {
                    "model": r.name,
                    "endpoint_hash": digest(r.endpoint),
                    "parameters": r.parameters,
                    "capabilities": r.capabilities,
                    "cache": r.cache,
                    "context_window": r.context_window,
                    "retries": r.max_retries,
                }
                for r in routes
            ]
            + [settings.main_instructions, settings.worker_instructions, fixture]
        )

    async def run(self, case, policy, root):
        workspace = self.workspace or root / "workspace"
        if self.workspace is None:
            materialize(case, workspace)
        settings = apply_policy(self.settings, policy)
        settings = replace(
            settings,
            shell_roots=(workspace,),
            skill_roots=(),
            mcp_servers={},
            http_tools={},
            browser={},
            computer={},
            coding_directory=None,
            cli_bin="/nonexistent/rsi-cli",
            professional_executor="",
            proactive_enabled=False,
        )
        budget = EpisodeBudget(case["limits"])
        providers = []
        for role in ("main", "worker", "memory"):
            if self.fixture:
                script = case.get("protocol_script") if role == "main" else None
                # Paths in scripts are relative to this fresh workspace.
                script = (
                    json.loads(json.dumps(script).replace("$WORKSPACE", str(workspace)))
                    if script
                    else None
                )
                provider = ProtocolFixtureModel(script)
            else:
                actual_role = "main" if role == "main" else "worker"
                route = settings.route(actual_role)
                output_cap = min(2048, route.parameters.get("max_tokens", 2048))
                route = replace(
                    route,
                    parameters=dict(route.parameters, max_tokens=output_cap),
                    max_retries=0,
                    timeout_seconds=min(case["limits"]["seconds"], route.timeout_seconds or 60),
                )
                configured = settings_with_route(settings, actual_role, route)
                provider = (
                    self.provider_factory(configured, role)
                    if self.provider_factory
                    else configured_provider(configured, actual_role)
                )
            providers.append(provider)
        journal = []
        models = [
            MeteredModel(p, budget, role, journal=journal)
            for p, role in zip(providers, ("main", "worker", "memory"), strict=True)
        ]
        database = Database(root / "runtime.db", root / "runtime", managed=False)
        await database.open()
        runtime = Runtime(
            database, models[0], settings=settings, worker_model=models[1], memory_model=models[2]
        )
        # No shell, delegations, external capabilities, session operations or grader access.
        allowed = {
            "read",
            "write",
            "edit",
            "tool_list",
            "reply",
            "file_read",
            "file_write",
            "file_patch",
            "artifact_read",
            "skill_read",
            "capability_overview",
        }
        if self.allow_shell:
            allowed.update({"bash", "shell"})
        runtime.tools.disabled_tools.update(set(runtime.tools.registry) - allowed)
        output, trace, failure = "", None, None
        turn_grades, traces, tool_records = [], [], []
        started = time.monotonic()
        verified_ms = None
        deferred_jobs = 0
        try:
            await runtime.start()
            async with asyncio.timeout(case["limits"]["seconds"]):
                conversation = await runtime.conversations.create("rsi-evaluation")
                prompts = [case["prompt"], *case.get("followups", [])]
                for index, prompt in enumerate(prompts):
                    receipt = await runtime.chat.submit(
                        "rsi-evaluation",
                        conversation["id"],
                        str(index),
                        prompt + "\n工作目录：" + str(workspace),
                    )
                    while True:
                        turn = await database.call(
                            lambda db, receipt=receipt: row(
                                db, "SELECT * FROM turns WHERE id=?", (receipt["turnId"],)
                            )
                        )
                        if turn["state"] in {"completed", "failed", "interrupted"}:
                            break
                        await asyncio.sleep(0.01)
                    traces.append(
                        await runtime.traces.get("rsi-evaluation", turn_id=receipt["turnId"])
                    )
                    if turn["state"] != "completed":
                        failure = "RSI_TURN_" + turn["state"].upper()
                        break
                    view = await runtime.conversations.messages(
                        "rsi-evaluation", conversation["id"]
                    )
                    answers = [
                        m
                        for m in view["messages"]
                        if m["role"] == "assistant" and m["content"].get("text")
                    ]
                    if "turn_judges" in case:
                        turn_grades.append(
                            judge_case(
                                {**case, "judge": case["turn_judges"][index]},
                                answers[-1]["content"]["text"] if answers else "",
                                workspace,
                            )
                        )
                messages = await runtime.conversations.messages(
                    "rsi-evaluation", conversation["id"]
                )
                final = [
                    m
                    for m in messages["messages"]
                    if m["role"] == "assistant" and m["content"].get("text")
                ]
                output = final[-1]["content"]["text"] if final else ""
                trace = await runtime.traces.get("rsi-evaluation", turn_id=receipt["turnId"])
                grade = judge_case(case, output, workspace)
                if turn_grades and not all(g["passed"] for g in turn_grades):
                    grade = next(g for g in turn_grades if not g["passed"])
                    grade["reason"] = "conversation_turn_assertion_failed"
                verified_ms = (time.monotonic() - started) * 1000
                # Drain extraction/compaction already caused by the episode before counting cost.
                await runtime.memory_jobs.scan()
                if self.settle_maintenance:
                    await database.call(
                        lambda db: db.execute(
                            "UPDATE jobs SET available_ms=? WHERE kind='memory.daily' AND state='queued'",
                            (now_ms(),),
                        ),
                        write=True,
                    )
                    runtime.wakeup.set()
                while await database.call(
                    lambda db: db.execute(
                        "SELECT COUNT(*) FROM jobs WHERE state='running' OR (state='queued' AND available_ms<=?)",
                        (now_ms(),),
                    ).fetchone()[0]
                ):
                    await asyncio.sleep(0.02)
                deferred_jobs = await database.call(
                    lambda db: db.execute(
                        "SELECT COUNT(*) FROM jobs WHERE state='queued' AND kind IN ('memory.daily','memory.extract','context.compact')"
                    ).fetchone()[0]
                )
        except (DomainError, TimeoutError) as error:
            failure = error.code if isinstance(error, DomainError) else "RSI_TIME_BUDGET"
        finally:
            await runtime.close()
            for provider in providers:
                if hasattr(provider, "close"):
                    await provider.close()
            tool_records = await database.call(
                lambda db: [
                    dict(item)
                    for item in db.execute(
                        "SELECT t.*,m.content_json AS result_json FROM tool_calls t "
                        "LEFT JOIN messages m ON m.id=t.result_message_id ORDER BY t.created_ms,t.id"
                    )
                ]
            )
            await database.close()
            private_json(root / "model-log.json", {"requests": journal, "source": "host_provider"})
            private_json(
                root / "execution-log.json",
                {
                    "traces": traces,
                    "tool_calls": tool_records,
                    "failure": failure,
                    "output": output,
                },
            )
        if failure:
            grade = judge_case({**case, "judge": {"kind": "numeric", "expected": 1}}, "", workspace)
            grade["reason"] = failure
        diagnostics = [trace_metrics(t) for t in traces]
        process_metrics = {
            k: sum(d.get(k, 0) for d in diagnostics)
            for k in ("tool_calls", "tool_failures", "discovery_calls", "context_ms", "tool_ms")
        }
        metrics = {
            **budget.metrics(),
            **(trace_metrics(trace) if trace else {}),
            **process_metrics,
            "elapsed_ms": round(verified_ms, 3)
            if verified_ms is not None and not failure
            else None,
            "episode_ms": round((time.monotonic() - started) * 1000, 3),
            "deadline_ms": case["limits"]["seconds"] * 1000,
            "right_censored": failure is not None or not grade["passed"],
            "deferred_maintenance_jobs": deferred_jobs,
            "maintenance_settlement": "episode_snapshot"
            if self.settle_maintenance
            else "calendar_deferred",
        }
        metrics["observed_tokens"] = metrics["tokens"]
        if diagnostics:
            metrics["first_committed_text_ms"] = diagnostics[0]["first_committed_text_ms"]
        if deferred_jobs:
            metrics["tokens"] = None
            metrics["token_coverage"] = "partial_deferred_maintenance"
        blockers = ["protocol_fixture"] if self.fixture else []
        if budget.unknown:
            blockers.append("unknown_provider_usage")
        if deferred_jobs:
            blockers.append("deferred_maintenance_not_measured")
        return {
            "grade": grade,
            "metrics": metrics,
            "output": output,
            "release_blockers": blockers,
            "execution_kind": "protocol_fixture" if self.fixture else "native_files",
            "verified_delivery": bool(
                grade["passed"] and not failure and case["counts_as_delivery"]
            ),
        }


class ExternalExecutor:
    def __init__(self, argv, *, model_hash):
        require(
            isinstance(argv, list) and bool(argv) and all(isinstance(s, str) and s for s in argv)
        )
        require(Path(argv[0]).is_absolute(), "RSI_WORKER_ABSOLUTE_COMMAND_REQUIRED")
        self.argv, self.model_hash = argv, model_hash

    async def run(self, case, policy, root):
        workspace = root / "workspace"
        materialize(case, workspace)
        private_json(
            root / "request.json",
            {
                "protocol": 1,
                "case": agent_view(case, workspace),
                "policy": policy,
                "origin": case.get("origin"),
                "response_path": str(root / "response.json"),
            },
        )
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"TMUX", "TMUX_PANE", "ROAMI_HOME", "ROAMI_DATA", "ROAMI_CONFIG"}
        }
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *self.argv,
            str(root / "request.json"),
            cwd=root,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        async def capture(stream, name):
            descriptor = os.open(
                root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "wb") as output:
                size = 0
                while chunk := await stream.read(65536):
                    size += len(chunk)
                    require(size <= 4_000_000, "RSI_LOG_TOO_LARGE")
                    output.write(chunk)

        readers = [
            asyncio.create_task(capture(stream, name))
            for stream, name in (
                (process.stdout, "worker-stdout.log"),
                (process.stderr, "worker-stderr.log"),
            )
        ]
        try:
            async with asyncio.timeout(case["limits"]["seconds"]):
                await asyncio.gather(process.wait(), *readers)
            require(process.returncode == 0, "RSI_EXTERNAL_WORKER_FAILED")
            response = load_json(root / "response.json", maximum=4_000_000)
            require(
                response.get("protocol") == 1 and response.get("case_id") == case["id"],
                "RSI_EXTERNAL_RESPONSE",
            )
            metrics = response["metrics"]
            require(
                type(metrics.get("tokens")) is int
                and 0 <= metrics["tokens"] <= case["limits"]["tokens"],
                "RSI_EXTERNAL_USAGE",
            )
            require(
                type(metrics.get("model_calls")) is int
                and 0 <= metrics["model_calls"] <= case["limits"]["requests"],
                "RSI_EXTERNAL_USAGE",
            )
            grade = validate_external_grade(response["grade"])
            elapsed = (time.monotonic() - started) * 1000
            return {
                "grade": grade,
                "metrics": {
                    **metrics,
                    "elapsed_ms": elapsed if grade["passed"] else None,
                    "right_censored": not grade["passed"],
                    "episode_ms": elapsed,
                },
                "verified_delivery": grade["passed"] and case["counts_as_delivery"],
                "execution_kind": "external_worker",
                "release_blockers": ["external_isolation_not_attested"],
                "evidence": response.get("evidence", {}),
            }
        finally:
            if process.returncode is None or any(not reader.done() for reader in readers):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            async with asyncio.timeout(3):
                await process.communicate()
