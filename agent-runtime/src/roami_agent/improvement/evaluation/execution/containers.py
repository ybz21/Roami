"""Disposable Docker execution, host-side metering, and post-exit artifact verification."""

import asyncio
import json
import os
import secrets
import stat
import tempfile
import time
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

from roami_agent.improvement.domain.contracts import digest, require
from roami_agent.improvement.evaluation.contracts import agent_view
from roami_agent.improvement.evaluation.execution.container_context import model_context
from roami_agent.improvement.evaluation.execution.executors import NativeFilesExecutor
from roami_agent.improvement.evaluation.grading import judge_case
from roami_agent.improvement.integrations.artifact_files import materialize, private_json
from roami_agent.improvement.integrations.json_documents import load_json
from roami_agent.improvement.integrations.measurements import EpisodeBudget
from roami_agent.improvement.integrations.model_gateway import ModelGateway
from roami_agent.protocol.errors import DomainError

IMAGE = "roami-rsi-eval:local"

# Docker creation plus the existing model-free verifier sandbox windows.
POST_TIMEOUT_ASSESSMENT_SECONDS = {"media": 360, "slides": 90}


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
        worker_route=None,
        main_route=None,
        shared_budget=None,
        shared_daily_limit=False,
    ):
        self.settings, self.image = settings, image
        if shared_daily_limit:
            require(
                all(
                    route is None or route == settings.route(role)
                    for route, role in (
                        (main_route, "main"),
                        (worker_route, "worker"),
                        (memory_route, "worker"),
                    )
                )
                and not generation_overrides
                and not output_caps,
                "RSI_POLICY_OUT_OF_RANGE",
            )
        self.artifact_reviewer = artifact_reviewer
        self.artifact_renderer = None
        self.model_hash = digest(
            [
                NativeFilesExecutor(settings).model_hash,
                "container-uds-v32-configured-image-roles",
                artifact_reviewer.content_hash if artifact_reviewer else None,
            ]
        )
        self.main_route = main_route
        if main_route is not None:
            self.model_hash = digest([self.model_hash, asdict(main_route)])
        self.worker_route = worker_route
        if worker_route is not None:
            self.model_hash = digest([self.model_hash, asdict(worker_route)])
        self.memory_route = memory_route
        if memory_route is not None:
            self.model_hash = digest([self.model_hash, asdict(memory_route)])
        image_route = worker_route or settings.route("worker")
        self.worker_image_input = {
            "enabled": image_route.capabilities.get("images") is True,
            "limits": image_route.image_limits,
        }
        main_image_route = main_route or settings.route("main")
        self.main_image_input = {
            "enabled": main_image_route.capabilities.get("images") is True,
            "limits": main_image_route.image_limits,
        }
        self.model_hash = digest([self.model_hash, self.main_image_input, self.worker_image_input])
        self.image_id = None
        self.provider_factory = provider_factory
        self.shared_budget = shared_budget
        self.shared_daily_limit = shared_daily_limit
        self.model_context = model_context(settings) if shared_daily_limit else None
        if shared_daily_limit:
            self.model_hash = digest(
                [self.model_hash, "shared_model_daily_limit", self.model_context]
            )
        self.source_root = Path(source_root).resolve() if source_root is not None else None
        self.regression_root = regression_root
        self.output_caps = output_caps or {}
        require(
            all(
                k in {"main", "worker", "memory"}
                and (v is None or type(v) is int and 512 <= v <= 1_000_000)
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
        from roami_agent.improvement.integrations.source_workspace import source_hash

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
            from roami_agent.improvement.evaluation.mechanisms import nodes

            selected = nodes(case["id"])
            if "selectors" in case["judge"]:
                require(case["judge"]["selectors"] == selected, "RSI_REGRESSION_PACK_CHANGED")
            return 0
        if self.shared_daily_limit:
            return 0
        from roami_agent.improvement.evaluation.artifact_review import needs_artifact_review

        extra = (
            self.artifact_reviewer.profile["max_tokens"]
            if self.artifact_reviewer and needs_artifact_review(case)
            else 0
        )
        return case["limits"]["tokens"] + extra

    async def preflight(self, *, model_inputs=True):
        try:
            detail = json.loads(await docker_command("image", "inspect", self.image))[0]
        except (DomainError, ValueError):
            raise DomainError("RSI_CONTAINER_IMAGE_REQUIRED") from None
        labels = detail.get("Config", {}).get("Labels") or {}
        if self.shared_daily_limit:
            require(
                labels.get("org.roami.rsi.shared-daily-policy") == "5",
                "RSI_CONTAINER_IMAGE_REQUIRED",
            )
        if model_inputs and self.main_image_input["enabled"]:
            require(
                labels.get("org.roami.rsi.model-image-input") == "1",
                "RSI_CONTAINER_IMAGE_REQUIRED",
            )
        if model_inputs and self.worker_image_input["enabled"]:
            require(
                (detail.get("Config", {}).get("Labels") or {}).get(
                    "org.roami.rsi.workspace-image-input"
                )
                == "1",
                "RSI_CONTAINER_IMAGE_REQUIRED",
            )
        self.image_id = detail["Id"]
        renderer_id = None
        if self.artifact_reviewer:
            expected = self.artifact_reviewer.profile["renderer_image"]
            if self.image_id == expected:
                self.artifact_renderer = self
            else:
                self.artifact_renderer = ContainerExecutor(self.settings, image=expected)
                await self.artifact_renderer.preflight(model_inputs=False)
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

    async def sandbox(
        self, workspace, program, *, input=None, timeout=60, runtime=False, copy_workspace=False
    ):
        if not self.image_id:
            await self.preflight()
        name = "roami-rsi-grade-" + secrets.token_hex(10)
        if copy_workspace:
            # Copy inside the sandbox so artifact symlinks never traverse the host filesystem.
            program = (
                "import shutil\n"
                'shutil.copytree("/replay-input", "/workspace", dirs_exist_ok=True, symlinks=True)\n'
                + program
            )
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
            f"type=bind,src={workspace},dst={'/replay-input' if copy_workspace else '/workspace'},readonly",
            *(
                [
                    "--tmpfs",
                    f"/workspace:rw,size=536870912,mode=0700,uid={os.getuid()},gid={os.getgid()}",
                ]
                if copy_workspace
                else []
            ),
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

    async def verify(
        self, case, workspace, output, *, started, evidence_root=None, after_timeout=False
    ):
        if after_timeout:
            require(
                case["judge"]["kind"] in POST_TIMEOUT_ASSESSMENT_SECONDS,
                "RSI_ARTIFACT_ASSESSMENT_UNSUPPORTED",
            )
            remaining = POST_TIMEOUT_ASSESSMENT_SECONDS[case["judge"]["kind"]]
        else:
            remaining = case["limits"]["seconds"] - (time.monotonic() - started)
        require(remaining > 0, "RSI_TIME_BUDGET")
        async with asyncio.timeout(remaining):
            kind = case["judge"]["kind"]
            if kind == "authored":
                from roami_agent.improvement.evaluation.authored_grading import grade_authored

                grade = await grade_authored(case, workspace, self)
            elif kind == "terminal":
                from roami_agent.improvement.evaluation.benchmarks.terminal_tasks import (
                    grade_terminal,
                )

                grade = await grade_terminal(case, workspace, self)
            elif kind == "python_contract":
                from roami_agent.improvement.evaluation.code_contract import grade_code_contract

                grade = await grade_code_contract(case, workspace, self)
            elif kind == "vectorization":
                from roami_agent.improvement.evaluation.benchmarks.vectorization import (
                    grade_vectorization,
                )

                grade = await grade_vectorization(case, workspace, self)
            elif kind == "media":
                from roami_agent.improvement.evaluation.benchmarks.media_tasks import grade_media

                grade = await grade_media(case, workspace, self)
            elif kind == "swe":
                from roami_agent.improvement.evaluation.benchmarks.swe_tasks import grade_swe

                grade = await grade_swe(case, workspace, self)
            elif kind == "slides":
                from roami_agent.improvement.evaluation.benchmarks.slide_tasks import grade_slides

                grade = await grade_slides(case, workspace, self)
            elif kind == "long_memory":
                from roami_agent.improvement.evaluation.benchmarks.long_memory import (
                    grade_long_memory,
                )

                grade = await grade_long_memory(case, workspace, self)
            elif kind == "company":
                from roami_agent.improvement.evaluation.benchmarks.company_tasks import (
                    grade_company,
                )

                require(evidence_root is not None, "RSI_COMPANY_SNAPSHOT_FAILED")
                grade = await grade_company(
                    case, workspace, self, state_path=evidence_root / "company-snapshot.json"
                )
            elif kind == "company_stock":
                from roami_agent.improvement.evaluation.benchmarks.stock_tasks import grade_stock

                require(evidence_root is not None, "RSI_COMPANY_SNAPSHOT_FAILED")
                grade = await grade_stock(case, self, root=evidence_root)
            else:
                grade = judge_case(case, output, workspace)
        if after_timeout:
            grade["artifact_assessment_after_timeout"] = True
        else:
            require(time.monotonic() - started < case["limits"]["seconds"], "RSI_TIME_BUDGET")
        return grade

    async def recover_execution(self, state, root):
        from roami_agent.improvement.evaluation.execution.interrupted_evidence import (
            snapshot_metadata,
            snapshot_program,
        )
        from roami_agent.improvement.integrations.artifact_paths import relative_file

        try:
            original = load_json(
                relative_file(root, "state/execution-log.json"), maximum=64_000_000
            )
            if (
                isinstance(original, dict)
                and isinstance(original.get("tool_calls"), list)
                and isinstance(original.get("traces"), list)
            ):
                return
        except (DomainError, OSError, ValueError):
            pass
        try:
            try:
                if not stat.S_ISREG((state / "runtime.db").lstat().st_mode):
                    return
            except FileNotFoundError:
                return
            # A copied sandbox keeps SQLite WAL recovery and artifact symlinks off the host.
            raw = await self.sandbox(state, snapshot_program(), copy_workspace=True, timeout=15)
            value = json.loads(raw)
            snapshot_metadata(value)
            private_json(root / "interrupted-execution-log.json", value)
        except (DomainError, OSError, TimeoutError, ValueError) as error:
            try:
                private_json(
                    root / "interrupted-execution-error.json",
                    {
                        "source": "interrupted_runtime_snapshot",
                        "complete": False,
                        "error": getattr(error, "code", "RSI_EXECUTION_SNAPSHOT_FAILED"),
                    },
                )
            except OSError:
                pass

    async def run(self, case, policy, root):
        if not self.image_id:
            await self.preflight()
        if case["judge"]["kind"] == "mechanism":
            from roami_agent.improvement.evaluation.mechanisms import run_mechanism

            return await run_mechanism(case, policy, root, self)
        started = time.monotonic()
        workspace, state = root / "workspace", root / "state"
        materialize(case, workspace)
        prepared_project = None
        if case["judge"]["kind"] == "swe":
            from roami_agent.improvement.evaluation.benchmarks.swe_tasks import (
                prepare_project,
                resolve_image,
            )

            await resolve_image(case["judge"]["image"])
            prepared_project = await asyncio.to_thread(prepare_project, case, workspace)
        elif case["judge"]["kind"] == "slides":
            from roami_agent.improvement.evaluation.benchmarks.slide_tasks import prepare_slides

            await asyncio.to_thread(prepare_slides, case, workspace)
        elif case["judge"]["kind"] == "long_memory":
            from roami_agent.improvement.evaluation.benchmarks.long_memory import prepare_history

            await asyncio.to_thread(prepare_history, case, workspace)
        elif case["judge"]["kind"] == "company":
            from roami_agent.improvement.evaluation.execution.company_environment import (
                resolve_images,
            )

            await resolve_images(case["judge"]["images"])
        elif case["judge"]["kind"] == "company_stock":
            from roami_agent.improvement.evaluation.execution.stock_environment import resolve_image

            await resolve_image(case["judge"]["image"])
        require(time.monotonic() - started < case["limits"]["seconds"], "RSI_TIME_BUDGET")
        state.mkdir(mode=0o700)
        view = agent_view(case, Path("/workspace"))
        from roami_agent.improvement.evaluation.execution.evaluation_tasks import (
            NATIVE_TASK_REQUEST,
        )

        view["prompt"] += (
            "\n"
            + NATIVE_TASK_REQUEST
            + "本任务在无网络的独立容器中执行，文件位于/workspace。每个任务都先委派Worker，包括简单数值答案和小型文件；target={kind:new_session,directory:/workspace}，routing.explicitExecutor=native，userQuote引用上面的明确指令。如实填写复杂度，不要为了选择Native而把复杂任务说成有界任务。不要连接专业CLI、其他节点或现用会话。Main只协调和报告结果，不执行shell、计算答案或写入交付文件。最终产物由容器外独立判定器验收，内部任务等待验收不代表最终得分。"
        )
        input_names = sorted(set(case.get("files", {})) | set(case.get("asset_files", {})))
        visible_inputs = []
        for filename in input_names:
            if len(json.dumps(visible_inputs + [filename], ensure_ascii=False).encode()) > 8000:
                break
            visible_inputs.append(filename)
        view["prompt"] += "\n输入文件目录：" + json.dumps(visible_inputs, ensure_ascii=False)
        if len(visible_inputs) < len(input_names):
            view["prompt"] += "（目录已截断；其余输入由Worker在工作区检索。）"
        view["followups"] = case.get("followups", [])
        private_json(
            state / "request.json",
            {
                "case": view,
                "policy": policy,
                "shared_daily_limit": self.shared_daily_limit,
                "worker_image_input": self.worker_image_input,
                "main_image_input": self.main_image_input,
                "model_context": self.model_context,
            },
        )
        setup_ms = (time.monotonic() - started) * 1000
        budget = EpisodeBudget(case["limits"], shared_daily_limit=self.shared_daily_limit)
        budget.started = started
        providers, models, journal = [], {}, []
        for role in ("main", "worker", "memory"):
            actual = "main" if role == "main" else "worker"
            route = (
                self.main_route
                if role == "main" and self.main_route is not None
                else self.memory_route
                if role == "memory" and self.memory_route is not None
                else self.worker_route
                if actual == "worker" and self.worker_route is not None
                else self.settings.route(actual)
            )
            from roami_agent.improvement.integrations.request_model import RequestBudgetModel

            if not self.shared_daily_limit:
                route = replace(
                    route,
                    max_retries=0,
                    parameters={**route.parameters, **self.generation_overrides.get(role, {})},
                )
            models[role] = RequestBudgetModel(
                self.settings,
                route,
                budget,
                role,
                cap=self.output_caps.get(role),
                factory=self.provider_factory,
                journal=journal,
                shared_budget=self.shared_budget,
            )
        name = "roami-rsi-agent-" + secrets.token_hex(10)
        failure = None
        response = {}
        review_budget = None
        artifact_review_ms = 0
        generation_elapsed = None
        created = False
        gateway_errors = []
        try:
            with tempfile.TemporaryDirectory(prefix="roami-rsi-gateway-") as directory:
                from roami_agent.improvement.evaluation.execution.company_runtime import (
                    company_runtime,
                )
                from roami_agent.improvement.evaluation.execution.project_runtime import (
                    project_runtime,
                )

                async with (
                    ModelGateway(Path(directory) / "gateway.sock", models) as gateway,
                    project_runtime(
                        case, directory, workspace, root, started + case["limits"]["seconds"]
                    ) as project,
                    company_runtime(
                        case, directory, workspace, root, started + case["limits"]["seconds"]
                    ) as company,
                ):
                    gateway_errors = gateway.errors
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
                    runtime_blockers = [
                        code
                        for code in response["release_blockers"]
                        if not (
                            self.shared_daily_limit
                            and budget.unknown
                            and code == "unknown_provider_usage"
                        )
                    ]
                    if gateway.errors:
                        failure = gateway.errors[0]
                    elif runtime_blockers:
                        from roami_agent.improvement.evaluation.execution.evaluation_tasks import (
                            NATIVE_EXECUTION_FAILURES,
                        )

                        failure = next(
                            (
                                c
                                for c in runtime_blockers
                                if isinstance(c, str) and c in NATIVE_EXECUTION_FAILURES
                            ),
                            "RSI_RUNTIME_REPORTED_FAILURE",
                        )
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
            if failure:
                await self.recover_execution(state, root)
            for provider in providers:
                if hasattr(provider, "close"):
                    await provider.close()
            private_json(
                root / "model-log.json",
                {
                    "requests": journal,
                    "source": "host_provider",
                    "gateway_errors": [
                        {"code": code, "count": count}
                        for code, count in sorted(Counter(gateway_errors).items())
                    ],
                },
            )
        assessment_ms = None
        if (
            failure == "RSI_TIME_BUDGET"
            and case["judge"]["kind"] in POST_TIMEOUT_ASSESSMENT_SECONDS
        ):
            # Generation stays stopped; this path only reads artifacts with the original verifier.
            assessment_started = time.monotonic()
            try:
                grade = await self.verify(
                    case, workspace, "", started=started, evidence_root=root, after_timeout=True
                )
            except (DomainError, OSError, TimeoutError, ValueError, TypeError, KeyError) as error:
                grade.update(
                    artifact_assessment_after_timeout=True,
                    native_verifier_ran=False,
                    artifact_assessment_error=error.code
                    if isinstance(error, DomainError)
                    else "RSI_ARTIFACT_ASSESSMENT_TIMEOUT"
                    if isinstance(error, TimeoutError)
                    else "RSI_ARTIFACT_ASSESSMENT_FAILED",
                )
            assessment_ms = (time.monotonic() - assessment_started) * 1000
            elapsed = (time.monotonic() - started) * 1000

        from roami_agent.improvement.evaluation.artifact_review import episode_metrics

        metrics = episode_metrics(budget, review_budget)
        if assessment_ms is not None:
            metrics["artifact_assessment_ms"] = assessment_ms
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
