"""Short Main tools bound to conversation-scoped application services."""

import json

from roami_agent.dispatch.routing import public_routing, routing_schema
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.storage.database import row
from roami_agent.storage.task_handoff import accepted_handoffs


def register_main_tools(registry, tasks, memory, targets, router=None):
    async def assert_session_inspection(session_id, binding):
        inspected = await tasks.db.call(
            lambda db: row(
                db,
                "SELECT m.content_json FROM tool_calls x JOIN messages m ON m.id=x.result_message_id "
                "WHERE x.turn_id=? AND x.tool_name='task_status' AND x.state='succeeded' "
                "ORDER BY x.rowid DESC LIMIT 1",
                (binding["turnId"],),
            )
        )
        if not inspected:
            return
        snapshot = json.loads(json.loads(inspected["content_json"])["text"])
        unresolved = [
            task
            for task in snapshot
            if (task.get("latestAttempt") or {}).get("outcomeKnown") is False
            or (task.get("latestAttempt") or {}).get("state") == "unknown"
        ]
        if unresolved and not any(
            session_id == (task.get("latestAttempt") or {}).get("sessionId") for task in unresolved
        ):
            raise DomainError("TASK_SESSION_BINDING_REQUIRED", 409)

    async def send_message(args, binding):
        await assert_session_inspection(args["sessionId"], binding)
        return await targets.send(
            args["sessionId"],
            args["text"],
            binding["turnId"] + ":" + binding["toolCallId"],
            binding=binding,
        )

    registry.add(
        Tool(
            "session_send",
            "Append the user's message or work instructions to one exact existing live session. "
            "Works with legacy Codex/Claude sessions without lifecycle callbacks. Returns delivery only, "
            "NOT task completion. replyExpected=true includes a durable dispatchId and a local CLI return channel for executor reports; "
            "executionTracked=false means no provider lifecycle proof. Wait for the report in Main, never claim completion from delivery. "
            "Use immediately when the user asks to message, hand work to, or continue an existing session; the request authorizes sending, so do not ask again. Resolve the destination using available context or discovery, never guess among ambiguous matches. "
            "For a new session/project or tracked task use delegate instead. Do not retry unknown outcomes.",
            object_schema(
                {
                    "sessionId": {"type": "string", "minLength": 1, "maxLength": 300},
                    "text": {"type": "string", "minLength": 1},
                },
                ["sessionId", "text"],
            ),
            send_message,
            main=True,
            effect="write",
        )
    )

    async def executor_catalog(args, binding):
        return await targets.executors(args.get("commands"))

    registry.add(
        Tool(
            "executor_catalog",
            "Discover local professional executors without starting them. Installation is not authentication, quota, or verification of specialized tools; unknown stays unknown.",
            object_schema(
                {
                    "commands": {
                        "type": "array",
                        "maxItems": 24,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "pattern": "^[A-Za-z0-9][A-Za-z0-9._+-]{0,100}$",
                        },
                    }
                }
            ),
            executor_catalog,
            main=True,
        )
    )

    async def dispatch_status(args, binding):
        return await targets.dispatches.status(
            binding["owner"], binding["conversation"], args["dispatchId"]
        )

    registry.add(
        Tool(
            "session_dispatch_status",
            "Read a delivered session assignment and its executor reports by dispatchId in this conversation. Missing reports remain unconfirmed; reports are not independent verification.",
            object_schema(
                {"dispatchId": {"type": "string", "minLength": 1, "maxLength": 200}}, ["dispatchId"]
            ),
            dispatch_status,
            main=True,
        )
    )

    async def ask_user(args, binding):
        labels = [option["label"].strip() for option in args["options"]]
        if len(set(labels)) != len(labels) or any(not label for label in labels):
            raise DomainError("INVALID_QUESTION_OPTIONS")
        return {"question": args, "state": "waiting_user"}

    registry.add(
        Tool(
            "ask_user",
            "Ask only when a real decision is missing. Supply 2-4 concrete options, recommended first. Never ask permission again for an already authorized session message or task. This ends the turn and waits for the user's selection; call this tool alone, then stop.",
            object_schema(
                {
                    "prompt": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "options": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 4,
                        "items": object_schema(
                            {
                                "label": {"type": "string", "minLength": 1, "maxLength": 160},
                                "description": {"type": "string", "maxLength": 300},
                            },
                            ["label"],
                        ),
                    },
                },
                ["prompt", "options"],
            ),
            ask_user,
            main=True,
        )
    )

    async def overview(args, binding):
        return await targets.overview()

    registry.add(
        Tool(
            "workspace_overview",
            "Count projects and sessions on the current Roami node in one CLI call. "
            "Includes project/loose and live/dormant session totals. Use for count or overview "
            "questions; do not count truncated project top cards or page through target_search.",
            object_schema({}),
            overview,
            main=True,
        )
    )

    async def target_search(args, binding):
        scope = {"project_id": args["projectId"]} if args.get("projectId") else {}
        return await targets.search(
            args["kind"],
            args.get("query", ""),
            offset=args.get("offset", 0),
            limit=args.get("limit", 10),
            **scope,
        )

    async def target_resolve(args, binding):
        return await targets.resolve(args["kind"], args["id"])

    registry.add(
        Tool(
            "target_search",
            "Find projects or live sessions by literal name/ID, with bounded pages. For sessions in a project, supply the discovered projectId; this queries the full membership, not the top-three summary. Use one exact unique match directly; never guess among duplicate names. session_send appends to legacy sessions; tracked task continuation requires lifecycle callbacks.",
            object_schema(
                {
                    "kind": {"type": "string", "enum": ["project", "session"]},
                    "query": {"type": "string", "maxLength": 200},
                    "projectId": {"type": "string", "minLength": 1, "maxLength": 300},
                    "offset": {"type": "integer", "minimum": 0, "maximum": 10000},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                ["kind"],
            ),
            target_search,
            main=True,
        )
    )
    registry.add(
        Tool(
            "target_resolve",
            "Resolve an exact project ID or live session ID/name/label; duplicate labels fail. Liveness does not prove a task finished or stopped.",
            object_schema(
                {
                    "kind": {"type": "string", "enum": ["project", "session"]},
                    "id": {"type": "string", "minLength": 1, "maxLength": 300},
                },
                ["kind", "id"],
            ),
            target_resolve,
            main=True,
        )
    )

    async def delegate(args, binding):
        decision = await router.decide(args, binding) if args.get("routing") and router else None
        executor = decision["executor"] if decision else args.get("executor", "native")
        target = args.get("target") or {}
        if target.get("kind") == "session" and not binding.get("taskId"):
            if "session_send" in registry.disabled_tools:
                raise DomainError("TOOL_DISABLED")
            if not target.get("sessionId"):
                raise DomainError("CODING_SESSION_ID_REQUIRED")
            if args.get("fromMessageId") or any(
                target.get(k) for k in ["directory", "workspaceId", "base", "remote"]
            ):
                raise DomainError("CODING_SESSION_TARGET_CONFLICT")
            destination = (
                decision["targetRef"]
                if decision
                else await targets.resolve("session", target["sessionId"])
            )
            await assert_session_inspection(destination["sessionId"], binding)
            result = await targets.send(
                destination["sessionId"],
                args["goal"],
                binding["turnId"] + ":" + binding["toolCallId"],
                binding=binding,
            )
            if decision:
                result["routingDecision"] = public_routing(decision)
            return result
        routing_args = {"routing_decision": decision} if decision else {}
        try:
            task = await tasks.create(
                binding["owner"],
                binding["conversation"],
                args["goal"],
                key=binding["turnId"] + ":" + binding["toolCallId"],
                **({"title": args["title"]} if "title" in args else {}),
                source_turn_id=binding["turnId"],
                source_assistant_message_id=binding["assistantMessageId"],
                parent_task_id=binding.get("taskId"),
                executor=executor,
                target=args.get("target"),
                from_message_id=args.get("fromMessageId"),
                origin_message_id=binding["originMessageId"],
                **routing_args,
            )
        except DomainError as exc:
            if exc.code != "TASK_FAILURE_REVIEW_REQUIRED":
                raise
            previous = await tasks.list(binding["owner"], binding["conversation"], for_model=True)
            evidence = [
                {
                    "taskId": item["id"],
                    "state": item["state"],
                    "revision": item["revision"],
                    "latestAttempt": item.get("latestAttempt"),
                }
                for item in previous
                if item.get("origin_message_id") == binding["originMessageId"]
            ][:3]
            return {
                "code": exc.code,
                "acceptedOnly": False,
                "state": "blocked",
                "tasks": evidence,
                "nextAction": "Inspect failure evidence and existing workspace. Do not create another task, "
                "change executor, or retry unknown writes automatically. Explain the blocker to the user; "
                "a corrected continuation must use task_steer on the existing task after user direction.",
            }
        stored_decision = json.loads(task["intent_json"]).get("routingDecision")
        return {
            "id": task["id"],
            "taskId": task["id"],
            "kind": "background_task",
            "executor": json.loads(task["intent_json"])["executor"],
            "state": task["state"],
            "acceptedOnly": task["state"]
            not in {"failed", "interrupted", "cancelled", "succeeded"},
            "delivery": "pending" if task["state"] == "queued" else "unconfirmed",
            **({"requestComplete": args["requestComplete"]} if "requestComplete" in args else {}),
            **({"routingDecision": public_routing(stored_decision)} if stored_decision else {}),
        }

    async def status(args, binding):
        handoffs = await tasks.db.call(lambda db: accepted_handoffs(db, binding.get("turnId")))
        if args.get("taskId") in handoffs:
            raise DomainError("TASK_ALREADY_HANDED_OFF", 409)
        items = await tasks.list(
            binding["owner"],
            binding["conversation"],
            for_model=True,
            task_id=args.get("taskId"),
            **({"exclude_task_ids": tuple(handoffs)} if handoffs else {}),
        )
        if handoffs and not items:
            raise DomainError("TASK_ALREADY_HANDED_OFF", 409)

        def annotate(db):
            turn = row(
                db, "SELECT created_ms,trigger_kind FROM turns WHERE id=?", (binding.get("turnId"),)
            )
            for item in items:
                if item.get("contextExcluded") or not item.get("intent_json"):
                    continue
                intent = json.loads(item["intent_json"])
                attempt = item.get("latestAttempt") or {}
                if intent.get("target", {}).get("resourceOnly") is not True or not attempt.get(
                    "runId"
                ):
                    continue
                captured = row(
                    db,
                    "SELECT MAX(captured_ms) AS latest FROM resource_observations WHERE task_id=? AND run_id=? "
                    "AND length(trim(json_extract(body_json,'$.domText')))>0",
                    (item["id"], attempt["runId"]),
                )["latest"]
                completion_report = bool(turn and turn["trigger_kind"] == "completion")
                fresh = bool(turn and captured and captured >= turn["created_ms"])
                attempt["retrievalEvidence"] = {
                    "lastRetrievedMs": captured,
                    "freshForCurrentRequest": None if completion_report else fresh,
                    "forCompletionReport": completion_report,
                    "recovery": (
                        "This is a completion callback, not a new lookup request or new authorization. "
                        "Report the committed task state and source evidence; do not steer or retry from this callback."
                        if completion_report
                        else "This task is already accepted and still pending. Its completion report will arrive automatically. "
                        "Do not poll status or steer it again for this same request. Handle any other requested parts, then end this turn."
                        if item["state"]
                        not in {"succeeded", "failed", "cancelled", "interrupted", "waiting_user"}
                        else "This attempt is no longer running and has source evidence captured after the current request. "
                        "Report its actual state, verified results and remaining limitations. Do not poll or rerun it for this same request."
                        if fresh
                        else "This is stored task status, not a fresh lookup. For a new lookup request, "
                        "continue this task with task_steer at its current revision and retrieve sources again. "
                        "Cached facts may answer an explicit recap/status request only; never present them as new retrieval."
                    ),
                }
            return items

        return await tasks.db.call(annotate)

    async def recall(args, binding):
        day = args.get("scope") == "day"
        day_key = args.get("dayKey")
        timezone = args.get("timezone") or memory.daily.timezone
        if day:
            from roami_agent.memory.daily import event_day
            from roami_agent.protocol.identity import now_ms

            day_key = day_key or event_day(now_ms(), timezone)
            await memory.daily.refresh(binding["owner"], day_key, timezone)
        result = await memory.recall(
            binding["owner"],
            "" if day else args["query"],
            conversation_id=binding["conversation"]
            if args.get("scope", "conversation") == "conversation"
            else None,
            project_id=args.get("projectId"),
            day_key=day_key if day else None,
            timezone=timezone if day else None,
            limit=8,
            include_global=not day,
        )
        packed, remaining = [], 6000
        for hit in result["hits"]:
            item = {
                "id": hit["id"],
                "title": hit["title"],
                "excerpt": hit["body"][:500],
                "revision": hit["revision"],
                "sourceRefs": hit["sourceRefs"],
                "scope": hit["scope"],
                "rankReason": hit["rankReason"],
            }
            size = len(encoded(item).encode())
            if size > remaining:
                result["truncated"] = True
                break
            packed.append(item)
            remaining -= size
        result["hits"] = packed
        return result

    async def recall_one(args, binding):
        hit = await memory.get(binding["owner"], args["memoryId"])
        offset = args.get("offset", 0)
        return {
            "id": hit["id"],
            "title": hit["title"],
            "body": hit["body"][offset : offset + 2000],
            "sources": hit["sources"],
            "nextOffset": offset + 2000 if len(hit["body"]) > offset + 2000 else None,
        }

    registry.add(
        Tool(
            "memory_get",
            "Read a source-backed memory in bounded pages.",
            object_schema(
                {"memoryId": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}},
                ["memoryId"],
            ),
            recall_one,
            main=True,
        )
    )

    registry.add(
        Tool(
            "delegate",
            "Delegate with routing={explicitExecutor:native|codex|claude|null,complexity:bounded|complex,complexityBasis:{dimension:fact},routingExplanation:reason}. "
            "Task kinds are open. Host selects native for bounded work and an available professional for complex work; source-backed explicit executors win. "
            "Omit executor for configured project/preference/node selection; requests without routing retain legacy defaults. "
            "Main session targets send directly, including legacy sessions without callbacks: delivery only. "
            "Other targets return queued background_task/taskId, not completion. Task/native-branch IDs are not session IDs. "
            "Continue tracked work with task_steer at its actual revision, preserving executor. fromMessageId forks completed checkpoints only.",
            object_schema(
                {
                    "goal": {"type": "string", "minLength": 1},
                    "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80,
                        "description": "Short topic; keep full requirements, paths and steps in goal.",
                    },
                    "requestComplete": {
                        "type": "boolean",
                        "description": "Required: true after all requested parts are handled/delegated; false only while other parts remain. Never wait or poll for delegated work.",
                    },
                    "routing": routing_schema(),
                    "executor": {"type": "string", "enum": ["native", "codex", "claude"]},
                    "target": {
                        **object_schema(
                            {
                                "kind": {
                                    "type": "string",
                                    "enum": ["project", "session", "new_session", "new_project"],
                                },
                                "projectId": {"type": "string", "minLength": 1, "maxLength": 300},
                                "sessionId": {"type": "string", "minLength": 1, "maxLength": 300},
                                "workspaceId": {"type": "string", "minLength": 1, "maxLength": 300},
                                "directory": {"type": "string", "maxLength": 2000},
                                "name": {"type": "string", "maxLength": 200},
                                "baseDir": {"type": "string", "maxLength": 2000},
                                "base": {"type": "string", "maxLength": 300},
                                "remote": {"type": "string", "maxLength": 300},
                                "nodeId": {"type": "string", "enum": ["local"]},
                                "label": {"type": "string", "maxLength": 160},
                                "archived": {"type": "boolean"},
                                "resourceOnly": {"type": "boolean"},
                                "state": {"type": "string", "enum": ["live"]},
                            },
                            ["kind"],
                        ),
                        "description": "Existing session: kind=session, exact sessionId (+nodeId/label); no directory/workspaceId/base/remote; projectId cannot override the session. Existing project: kind=project, discovered projectId; workspaceId reuses work without base/remote/directory overrides. Loose work: kind=new_session, directory=actual absolute work directory, NEVER baseDir. File output does not authorize a new project. Use kind=new_project, name (+existing absolute baseDir) ONLY when the user requests a new project. Resolve actual project IDs; ask for missing destinations, never invent paths. Reuse preserves local work.",
                    },
                    "fromMessageId": {"type": "string"},
                },
                ["goal", "requestComplete"],
            ),
            delegate,
            effect="write",
            main=True,
        )
    )

    async def steer_task(args, binding):
        handoffs = await tasks.db.call(lambda db: accepted_handoffs(db, binding.get("turnId")))
        if args["taskId"] in handoffs:
            raise DomainError("TASK_ALREADY_HANDED_OFF", 409)
        receipt = await tasks.revisions.request(
            binding["owner"],
            args["taskId"],
            args["text"],
            args["revision"],
            binding["turnId"] + ":" + binding["toolCallId"],
            source_turn_id=binding["turnId"],
            source_conversation_id=binding["conversation"],
        )
        return {
            **receipt,
            "acceptedOnly": receipt["state"] in {"stopping", "applied"},
            "kind": "task_continuation",
            **({"requestComplete": args["requestComplete"]} if "requestComplete" in args else {}),
        }

    registry.add(
        Tool(
            "task_steer",
            "Continue a known tracked task with additional user requirements at its actual revision. Preserves its executor and source; waits for stop proof. This cannot switch executors or use a tmux sessionId. Queue acceptance is not completion.",
            object_schema(
                {
                    "taskId": {"type": "string", "minLength": 1, "maxLength": 200},
                    "revision": {"type": "integer", "minimum": 1},
                    "requestComplete": {
                        "type": "boolean",
                        "description": "Required: true after all requested parts are handled/delegated; false only while other parts remain. Never wait or poll for delegated work.",
                    },
                    "text": {"type": "string", "minLength": 1},
                },
                ["taskId", "revision", "text", "requestComplete"],
            ),
            steer_task,
            main=True,
            effect="write",
        )
    )

    async def cancel_task(args, binding):
        return await tasks.cancel(binding["owner"], args["taskId"])

    registry.add(
        Tool(
            "task_cancel",
            "Cancel an owned delegated background task. This does not retract a delivered message or kill an unrelated working session.",
            object_schema(
                {"taskId": {"type": "string", "minLength": 1, "maxLength": 200}}, ["taskId"]
            ),
            cancel_task,
            effect="write",
            main=True,
        )
    )
    registry.add(
        Tool(
            "task_status",
            "Read delegated task status in this conversation. Optionally filter by an exact taskId.",
            object_schema({"taskId": {"type": "string", "minLength": 1, "maxLength": 200}}),
            status,
            main=True,
        )
    )
    registry.add(
        Tool(
            "memory_search",
            "Retrieve source-backed memories only when relevant.",
            object_schema(
                {
                    "query": {"type": "string", "maxLength": 1000},
                    "scope": {"type": "string", "enum": ["conversation", "user", "day"]},
                    "projectId": {"type": "string"},
                    "dayKey": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
                    "timezone": {"type": "string", "maxLength": 100},
                },
                ["query"],
            ),
            recall,
            main=True,
        )
    )
