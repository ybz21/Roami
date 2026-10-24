"""Disposable Docker execution, host-side metering, and post-exit artifact verification."""

import asyncio
import json
import os
import secrets
import tempfile
import time
from dataclasses import asdict, replace
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


async def docker_command(*args, timeout=30, input=None, maximum=8_000_000):
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
                    require(size <= maximum, "RSI_DOCKER_OUTPUT_LIMIT")
                    chunks.append(chunk)
                return b"".join(chunks)

            out, _err = await asyncio.gather(bounded(process.stdout), bounded(process.stderr))
            await process.wait()
        require(process.returncode == 0, "RSI_DOCKER_COMMAND_FAILED")
        require(len(out) <= maximum, "RSI_DOCKER_OUTPUT_LIMIT")
        return out
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def remove_container(name, label):
    data = json.loads(await docker_command("inspect", name))[0]
    require(data["Config"]["Labels"].get("roami.rsi") == label, "RSI_CONTAINER_IDENTITY_CHANGED")
    await docker_command("rm", "--force", "--volumes", name)


class ContainerExecutor:
    def __init__(
        self,
        settings,
        *,
        image=IMAGE,
        provider_factory=None,
        source_root=None,
        regression_root=None,
        artifact_reviewer=None,
        output_caps=None,
        generation_overrides=None,
        memory_route=None,
    ):
        self.settings, self.image = settings, image
        self.artifact_reviewer = artifact_reviewer
        self.artifact_renderer = None
        self.model_hash = digest(
            [
                NativeFilesExecutor(settings).model_hash,
                "container-uds-v2-main-worker",
                artifact_reviewer.content_hash if artifact_reviewer else None,
            ]
        )
        self.memory_route = memory_route
        if memory_route is not None:
            self.model_hash = digest([self.model_hash, asdict(memory_route)])
        self.image_id = None
        self.provider_factory = provider_factory
        self.source_root = Path(source_root).resolve() if source_root is not None else None
        self.regression_root = regression_root
        self.output_caps = output_caps or {}
        require(
            all(
                k in {"main", "worker", "memory"} and type(v) is int and 512 <= v <= 16384
                for k, v in self.output_caps.items()
            ),
            "RSI_POLICY_OUT_OF_RANGE",
        )
        from roami_agent.providers.generation_parameters import generation_parameters

        self.generation_overrides = generation_overrides or {}
        require(
            set(self.generation_overrides) <= {"main", "worker", "memory"},
            "RSI_POLICY_OUT_OF_RANGE",
        )
        for parameters in self.generation_overrides.values():
            generation_parameters(parameters)
            require("max_tokens" not in parameters, "RSI_POLICY_OUT_OF_RANGE")
        if self.generation_overrides:
            self.model_hash = digest([self.model_hash, self.generation_overrides])
        if self.output_caps:
            self.model_hash = digest([self.model_hash, self.output_caps])

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

            selected = nodes(case["id"])
            if "selectors" in case["judge"]:
                require(case["judge"]["selectors"] == selected, "RSI_REGRESSION_PACK_CHANGED")
            return 0
        from roami_agent.improvement.artifact_review import needs_artifact_review

        extra = (
            self.artifact_reviewer.profile["max_tokens"]
            if self.artifact_reviewer and needs_artifact_review(case)
            else 0
        )
        return case["limits"]["tokens"] + extra

    async def preflight(self):
        try:
            detail = json.loads(await docker_command("image", "inspect", self.image))[0]
        except (DomainError, ValueError):
            raise DomainError("RSI_CONTAINER_IMAGE_REQUIRED") from None
        self.image_id = detail["Id"]
        renderer_id = None
        if self.artifact_reviewer:
            expected = self.artifact_reviewer.profile["renderer_image"]
            if self.image_id == expected:
                self.artifact_renderer = self
            else:
                self.artifact_renderer = ContainerExecutor(self.settings, image=expected)
                await self.artifact_renderer.preflight()
            renderer_id = self.artifact_renderer.image_id
            require(renderer_id == expected, "RSI_ARTIFACT_RENDERER_CHANGED")
        return {
            "image_id": self.image_id,
            "artifact_renderer_image_id": renderer_id,
            "environment_hash": digest(
                [self.image_id, renderer_id, "network-none", "nonroot-readonly-v1"]
            ),
        }

    async def remove(self, name, label):
        await remove_container(name, label)

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

    async def verify(self, case, workspace, output, *, started, evidence_root=None):
        remaining = case["limits"]["seconds"] - (time.monotonic() - started)
        require(remaining > 0, "RSI_TIME_BUDGET")
        async with asyncio.timeout(remaining):
            kind = case["judge"]["kind"]
            if kind == "authored":
                from roami_agent.improvement.authored_grading import grade_authored

                grade = await grade_authored(case, workspace, self)
            elif kind == "terminal":
                from roami_agent.improvement.terminal_tasks import grade_terminal

                grade = await grade_terminal(case, workspace, self)
            elif kind == "python_contract":
                from roami_agent.improvement.code_contract import grade_code_contract

                grade = await grade_code_contract(case, workspace, self)
            elif kind == "vectorization":
                from roami_agent.improvement.vectorization import grade_vectorization

                grade = await grade_vectorization(case, workspace, self)
            elif kind == "media":
                from roami_agent.improvement.media_tasks import grade_media

                grade = await grade_media(case, workspace, self)
            elif kind == "swe":
                from roami_agent.improvement.swe_tasks import grade_swe

                grade = await grade_swe(case, workspace, self)
            elif kind == "slides":
                from roami_agent.improvement.slide_tasks import grade_slides

                grade = await grade_slides(case, workspace, self)
            elif kind == "long_memory":
                from roami_agent.improvement.long_memory import grade_long_memory

                grade = await grade_long_memory(case, workspace, self)
            elif kind == "company":
                from roami_agent.improvement.company_tasks import grade_company

                require(evidence_root is not None, "RSI_COMPANY_SNAPSHOT_FAILED")
                grade = await grade_company(
                    case, workspace, self, state_path=evidence_root / "company-snapshot.json"
                )
            elif kind == "company_stock":
                from roami_agent.improvement.stock_tasks import grade_stock

                require(evidence_root is not None, "RSI_COMPANY_SNAPSHOT_FAILED")
                grade = await grade_stock(case, self, root=evidence_root)
            else:
                grade = judge_case(case, output, workspace)
        require(time.monotonic() - started < case["limits"]["seconds"], "RSI_TIME_BUDGET")
        return grade

    async def run(self, case, policy, root):
        if not self.image_id:
            await self.preflight()
        if case["judge"]["kind"] == "mechanism":
            from roami_agent.improvement.mechanisms import run_mechanism

            return await run_mechanism(case, policy, root, self)
        started = time.monotonic()
        workspace, state = root / "workspace", root / "state"
        materialize(case, workspace)
        prepared_project = None
        if case["judge"]["kind"] == "swe":
            from roami_agent.improvement.swe_tasks import prepare_project, resolve_image

            await resolve_image(case["judge"]["image"])
            prepared_project = await asyncio.to_thread(prepare_project, case, workspace)
        elif case["judge"]["kind"] == "slides":
            from roami_agent.improvement.slide_tasks import prepare_slides

            await asyncio.to_thread(prepare_slides, case, workspace)
        elif case["judge"]["kind"] == "long_memory":
            from roami_agent.improvement.long_memory import prepare_history

            await asyncio.to_thread(prepare_history, case, workspace)
        elif case["judge"]["kind"] == "company":
            from roami_agent.improvement.company_environment import resolve_images

            await resolve_images(case["judge"]["images"])
        elif case["judge"]["kind"] == "company_stock":
            from roami_agent.improvement.stock_environment import resolve_image

            await resolve_image(case["judge"]["image"])
        require(time.monotonic() - started < case["limits"]["seconds"], "RSI_TIME_BUDGET")
        state.mkdir(mode=0o700)
        view = agent_view(case, Path("/workspace"))
        view["prompt"] += (
            "\n本任务在无网络的独立容器中执行，文件位于/workspace。Main没有可直接执行shell的工作区上下文，不要尝试或重试Main的bash。涉及代码、脚本或批处理时直接委派默认Worker，target={kind:new_session,directory:/workspace}。环境使用native是执行器元信息，不是用户明确指定执行器：routing.explicitExecutor=null，不填写userQuote。不要连接专业CLI、其他节点或现用会话。文件读取和小型写入可直接完成。最终产物由容器外独立判定器验收，内部任务等待验收不代表最终得分。"
        )
        view["followups"] = case.get("followups", [])
        private_json(state / "request.json", {"case": view, "policy": policy})
        setup_ms = (time.monotonic() - started) * 1000
        budget = EpisodeBudget(case["limits"])
        budget.started = started
        providers, models, journal = [], {}, []
        for role in ("main", "worker", "memory"):
            actual = "main" if role == "main" else "worker"
            route = (
                self.memory_route
                if role == "memory" and self.memory_route is not None
                else self.settings.route(actual)
            )
            cap = self.output_caps.get(role, min(4096, route.parameters.get("max_tokens", 4096)))
            route = replace(
                route,
                max_retries=0,
                parameters={
                    **route.parameters,
                    **self.generation_overrides.get(role, {}),
                    "max_tokens": cap,
                },
            )
            settings = settings_with_route(self.settings, actual, route)
            provider = (
                self.provider_factory(settings, role)
                if self.provider_factory
                else configured_provider(settings, actual)
            )
            providers.append(provider)
            models[role] = MeteredModel(provider, budget, role, output_cap=cap, journal=journal)
        name = "roami-rsi-agent-" + secrets.token_hex(10)
        failure = None
        response = {}
        review_budget = None
        artifact_review_ms = 0
        generation_elapsed = None
        created = False
        try:
            with tempfile.TemporaryDirectory(prefix="roami-rsi-gateway-") as directory:
                from roami_agent.improvement.company_runtime import company_runtime
                from roami_agent.improvement.project_runtime import project_runtime

                async with (
                    ModelGateway(Path(directory) / "gateway.sock", models) as gateway,
                    project_runtime(
                        case, directory, workspace, root, started + case["limits"]["seconds"]
                    ) as project,
                    company_runtime(
                        case, directory, workspace, root, started + case["limits"]["seconds"]
                    ) as company,
                ):
                    setup_ms = (time.monotonic() - started) * 1000
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
                    remaining = case["limits"]["seconds"] - (time.monotonic() - started)
                    require(remaining > 0, "RSI_TIME_BUDGET")
                    await docker_command("start", "--attach", name, timeout=remaining)
                    response = load_json(state / "response.json", maximum=4_000_000)
                    require(
                        isinstance(response.get("release_blockers"), list),
                        "RSI_RUNTIME_RESPONSE_INVALID",
                    )
                    if gateway.errors:
                        failure = gateway.errors[0]
                    elif response["release_blockers"]:
                        failure = "RSI_RUNTIME_REPORTED_FAILURE"
                if project is not None and any(
                    r["state"] in {"running", "unknown"} for r in project.records
                ):
                    failure = "RSI_PROJECT_RUNTIME_UNSETTLED"
                if company is not None and any(
                    r["state"] in {"running", "unknown"} for r in company.records
                ):
                    failure = "RSI_COMPANY_RUNTIME_UNSETTLED"
                await self.remove(name, name)
                created = False
            grade = await self.verify(
                case, workspace, response.get("output", ""), started=started, evidence_root=root
            )
            generation_elapsed = (time.monotonic() - started) * 1000
            if (
                grade.get("pending")
                and grade.get("hard_passed")
                and self.artifact_reviewer
                and not failure
            ):
                review_started = time.monotonic()
                review_budget = self.artifact_reviewer.budget()
                grade = await self.artifact_reviewer.review(
                    case,
                    grade,
                    root,
                    self.artifact_renderer or self,
                    budget=review_budget,
                    journal=journal,
                )
                artifact_review_ms = (time.monotonic() - review_started) * 1000
            elapsed = (time.monotonic() - started) * 1000
        except (DomainError, OSError, TimeoutError, ValueError) as error:
            failure = (
                error.code
                if isinstance(error, DomainError)
                else (
                    "RSI_TIME_BUDGET" if isinstance(error, TimeoutError) else "RSI_CONTAINER_FAILED"
                )
            )
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
        from roami_agent.improvement.artifact_review import episode_metrics

        metrics = episode_metrics(budget, review_budget)
        metrics["artifact_review_ms"] = artifact_review_ms
        metrics["fixture_setup_ms"] = setup_ms
        if case["judge"]["kind"] == "swe":
            log = root / "project-runtime-log.json"
            records = load_json(log)["tool_calls"] if log.exists() else []
            metrics["project_source"] = prepared_project
            metrics["project_test_calls"] = len(records)
            metrics["project_test_ms"] = sum(r["elapsed_ms"] for r in records)
        if case["judge"]["kind"] in {"company", "company_stock"}:
            log = root / "company-runtime-log.json"
            data = load_json(log) if log.exists() else {"tool_calls": [], "native_http_calls": 0}
            metrics["company_api_calls"] = len(data["tool_calls"])
            metrics["company_api_ms"] = sum(r["elapsed_ms"] for r in data["tool_calls"])
            metrics["company_native_http_calls"] = data["native_http_calls"]
        if failure:
            grade.update(
                artifact_assessment=dict(grade),
                artifact_check_reason=grade.get("reason"),
                reason=failure,
                execution_error=failure,
                quality=0,
                passed=False,
                hard_passed=False,
                pending=False,
            )
        metrics.update(
            elapsed_ms=(generation_elapsed if generation_elapsed is not None else elapsed)
            if grade["passed"] and not failure
            else None,
            episode_ms=elapsed,
            right_censored=not grade["passed"] or bool(failure),
            process_diagnostics=response.get("metrics", {}),
            process_diagnostics_attested=False,
        )
        blockers = [failure] if failure else []
        if budget.unknown:
            blockers.append("unknown_provider_usage")
        if review_budget and review_budget.unknown:
            blockers.append("unknown_artifact_review_usage")
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
                "runtime_profile": "main_and_native_worker",
                **(
                    {"artifact_review": self.artifact_reviewer.content_hash}
                    if review_budget
                    else {}
                ),
                **(
                    {"project_runtime": case["judge"]["image"]}
                    if case["judge"]["kind"] == "swe"
                    else {}
                ),
                **(
                    {
                        "company_runtime": case["judge"].get("images", case["judge"].get("image")),
                        "service_network": "internal_unpublished",
                    }
                    if case["judge"]["kind"] in {"company", "company_stock"}
                    else {}
                ),
            },
        }
