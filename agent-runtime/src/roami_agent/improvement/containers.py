"""Disposable Docker execution, host-side metering, and post-exit artifact verification."""

import asyncio
import json
import os
import secrets
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from roami_agent.app import configured_provider
from roami_agent.improvement.contracts import agent_view, digest, load_json, require
from roami_agent.improvement.executors import NativeFilesExecutor, materialize, private_json
from roami_agent.improvement.grading import judge_case
from roami_agent.improvement.measurements import EpisodeBudget, MeteredModel
from roami_agent.improvement.model_gateway import ModelGateway
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.model_routes import settings_with_route

IMAGE = "roami-rsi-eval:local"


async def docker_command(*args, timeout=30, input=None):
    process = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdin=asyncio.subprocess.PIPE if input is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(timeout):
            if input is not None:
                process.stdin.write(input)
                await process.stdin.drain()
                process.stdin.close()

            async def bounded(stream):
                chunks, size = [], 0
                while chunk := await stream.read(65536):
                    size += len(chunk)
                    require(size <= 8_000_000, "RSI_DOCKER_OUTPUT_LIMIT")
                    chunks.append(chunk)
                return b"".join(chunks)

            out, _err = await asyncio.gather(bounded(process.stdout), bounded(process.stderr))
            await process.wait()
        require(process.returncode == 0, "RSI_DOCKER_COMMAND_FAILED")
        require(len(out) <= 8_000_000, "RSI_DOCKER_OUTPUT_LIMIT")
        return out
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


class ContainerExecutor:
    def __init__(
        self,
        settings,
        *,
        image=IMAGE,
        provider_factory=None,
        source_root=None,
        regression_root=None,
    ):
        self.settings, self.image = settings, image
        self.model_hash = digest([NativeFilesExecutor(settings).model_hash, "container-uds-v1"])
        self.image_id = None
        self.provider_factory = provider_factory
        self.source_root = Path(source_root).resolve() if source_root is not None else None
        self.regression_root = regression_root

    def source_mounts(self):
        if self.source_root is None:
            return []
        from roami_agent.improvement.source_revision import source_hash

        source_hash(self.source_root)
        package = self.source_root / "agent-runtime" / "src" / "roami_agent"
        mounts = []
        # Keep the image's evaluator package, where fixture and oracle modules were removed.
        for child in sorted(package.iterdir()):
            if child.name in {"improvement", "__pycache__"}:
                continue
            require(not child.is_symlink() and "," not in str(child), "RSI_SOURCE_MOUNT_INVALID")
            mounts.extend(
                [
                    "--mount",
                    f"type=bind,src={child},dst=/opt/roami-agent/src/roami_agent/{child.name},readonly",
                ]
            )
        return mounts

    def reservation_tokens(self, case):
        if case["judge"]["kind"] == "mechanism":
            from roami_agent.improvement.mechanisms import nodes

            nodes(case["id"])
            return 0
        return case["limits"]["tokens"]

    async def preflight(self):
        try:
            detail = json.loads(await docker_command("image", "inspect", self.image))[0]
        except (DomainError, ValueError):
            raise DomainError("RSI_CONTAINER_IMAGE_REQUIRED") from None
        self.image_id = detail["Id"]
        return {
            "image_id": self.image_id,
            "environment_hash": digest([self.image_id, "network-none", "nonroot-readonly-v1"]),
        }

    async def remove(self, name, label):
        data = json.loads(await docker_command("inspect", name))[0]
        require(
            data["Config"]["Labels"].get("roami.rsi") == label, "RSI_CONTAINER_IDENTITY_CHANGED"
        )
        await docker_command("rm", "--force", name)

    async def sandbox(self, workspace, program, *, input=None, timeout=60, runtime=False):
        if not self.image_id:
            await self.preflight()
        name = "roami-rsi-grade-" + secrets.token_hex(10)
        await docker_command(
            "create",
            "--interactive",
            "--name",
            name,
            "--label",
            "roami.rsi=" + name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--memory",
            "2g",
            "--cpus",
            "2",
            "--pids-limit",
            "256",
            "--tmpfs",
            "/tmp:rw,exec,size=536870912,mode=1777"
            if runtime
            else "/tmp:rw,size=536870912,mode=1777",
            "--shm-size",
            "256m",
            "--mount",
            f"type=bind,src={workspace},dst=/workspace,readonly",
            "-e",
            "HOME=/tmp/home",
            "--workdir",
            "/workspace",
            "--entrypoint",
            "python",
            *(self.source_mounts() if runtime else []),
            *(
                [
                    "--mount",
                    f"type=bind,src={self.regression_root},dst=/opt/roami-agent/tests,readonly",
                ]
                if runtime and self.regression_root
                else []
            ),
            self.image_id,
            "-c",
            program,
            timeout=30,
        )
        try:
            return await docker_command(
                "start", "--attach", "--interactive", name, timeout=timeout, input=input
            )
        finally:
            await self.remove(name, name)

    async def run(self, case, policy, root):
        if not self.image_id:
            await self.preflight()
        if case["judge"]["kind"] == "mechanism":
            from roami_agent.improvement.mechanisms import run_mechanism

            return await run_mechanism(case, policy, root, self)
        workspace, state = root / "workspace", root / "state"
        materialize(case, workspace)
        state.mkdir(mode=0o700)
        view = agent_view(case, Path("/workspace"))
        view["prompt"] += (
            "\n本任务在无网络的独立工作区执行，可直接使用文件与bash工具。按要求生成真实产物；不要等待其他执行器。"
        )
        view["followups"] = case.get("followups", [])
        private_json(state / "request.json", {"case": view, "policy": policy})
        budget = EpisodeBudget(case["limits"])
        providers, models, journal = [], {}, []
        for role in ("main", "worker", "memory"):
            actual = "main" if role == "main" else "worker"
            route = self.settings.route(actual)
            cap = min(4096, route.parameters.get("max_tokens", 4096))
            route = replace(route, max_retries=0, parameters=dict(route.parameters, max_tokens=cap))
            settings = settings_with_route(self.settings, actual, route)
            provider = (
                self.provider_factory(settings, role)
                if self.provider_factory
                else configured_provider(settings, actual)
            )
            providers.append(provider)
            models[role] = MeteredModel(provider, budget, role, output_cap=cap, journal=journal)
        name = "roami-rsi-agent-" + secrets.token_hex(10)
        started, failure = time.monotonic(), None
        response = {}
        created = False
        try:
            with tempfile.TemporaryDirectory(prefix="roami-rsi-gateway-") as directory:
                async with ModelGateway(Path(directory) / "gateway.sock", models) as gateway:
                    await docker_command(
                        "create",
                        "--name",
                        name,
                        "--label",
                        "roami.rsi=" + name,
                        "--network",
                        "none",
                        "--read-only",
                        "--cap-drop",
                        "ALL",
                        "--security-opt",
                        "no-new-privileges",
                        "--user",
                        f"{os.getuid()}:{os.getgid()}",
                        "--memory",
                        "2g",
                        "--cpus",
                        "2",
                        "--pids-limit",
                        "256",
                        "--tmpfs",
                        "/tmp:rw,size=536870912,mode=1777",
                        "--shm-size",
                        "256m",
                        "--mount",
                        f"type=bind,src={workspace},dst=/workspace",
                        "--mount",
                        f"type=bind,src={state},dst=/state",
                        "--mount",
                        f"type=bind,src={directory},dst=/model,readonly",
                        "-e",
                        "HOME=/tmp/home",
                        "-e",
                        "ROAMI_RSI_CONTAINER=1",
                        *self.source_mounts(),
                        self.image_id,
                    )
                    created = True
                    await docker_command(
                        "start", "--attach", name, timeout=case["limits"]["seconds"] + 10
                    )
                    response = load_json(state / "response.json", maximum=4_000_000)
                    if gateway.errors:
                        failure = gateway.errors[0]
                await self.remove(name, name)
                created = False
            if case["judge"]["kind"] == "authored":
                from roami_agent.improvement.authored_grading import grade_authored

                grade = await grade_authored(case, workspace, self)
            else:
                grade = judge_case(case, response.get("output", ""), workspace)
            elapsed = (time.monotonic() - started) * 1000
        except (DomainError, OSError, TimeoutError, ValueError) as error:
            failure = error.code if isinstance(error, DomainError) else "RSI_CONTAINER_FAILED"
            grade = {
                "quality": 0,
                "passed": False,
                "pending": False,
                "hard_passed": False,
                "reason": failure,
            }
            elapsed = (time.monotonic() - started) * 1000
        finally:
            if created:
                await self.remove(name, name)
            for provider in providers:
                if hasattr(provider, "close"):
                    await provider.close()
            private_json(root / "model-log.json", {"requests": journal, "source": "host_provider"})
        metrics = budget.metrics()
        metrics.update(
            elapsed_ms=elapsed if grade["passed"] and not failure else None,
            episode_ms=elapsed,
            right_censored=not grade["passed"] or bool(failure),
            process_diagnostics=response.get("metrics", {}),
            process_diagnostics_attested=False,
        )
        blockers = [failure] if failure else []
        if budget.unknown:
            blockers.append("unknown_provider_usage")
        return {
            "grade": grade,
            "metrics": metrics,
            "execution_kind": "isolated_native_worker",
            "verified_delivery": bool(
                grade["passed"] and not failure and case["counts_as_delivery"]
            ),
            "release_blockers": blockers,
            "isolation": {
                "image_id": self.image_id,
                "network": "none",
                "read_only_root": True,
                "host_grader_after_exit": True,
                "provider_keys_in_container": False,
            },
        }
