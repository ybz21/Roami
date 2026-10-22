"""Validate Main's semantic assessment against source-bound targets and executors."""

import json

from roami_agent.dispatch.workflow_preferences import workspace_preference
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import object_schema
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import event, row

EXECUTORS = {"native", "codex", "claude"}


def routing_schema():
    text = {"type": "string", "minLength": 1, "maxLength": 600}
    return object_schema(
        {
            "explicitExecutor": {
                "type": ["string", "null"],
                "enum": [None, *sorted(EXECUTORS)],
                "description": "Required on every assessment: the user's explicitly requested executor, or null only when the user made no executor choice. Never put the choice only in goal or routingExplanation.",
            },
            "taskDescription": {**text, "maxLength": 1000},
            "complexity": {
                "type": "string",
                "enum": ["bounded", "complex"],
                "description": "Execution burden: "
                "complex requires autonomous planning, exploring unknowns, coordinating dependencies "
                "or feedback-driven revision. bounded requires a procedure known BEFORE work, not just a known symptom or narrow goal. "
                "Must agree with complexityBasis/routingExplanation. Finite deliverables can be complex.",
            },
            "complexityBasis": {
                "type": "object",
                "minProperties": 1,
                "maxProperties": 8,
                "additionalProperties": text,
            },
            "routingExplanation": text,
            "userQuote": {
                **text,
                "description": "Exact source quote for a non-null explicitExecutor only. Omit when explicitExecutor is null; this is not a general task quote.",
            },
            "preference": object_schema(
                {
                    "executor": {"type": "string", "enum": sorted(EXECUTORS)},
                    "memoryId": text,
                    "revision": {"type": "integer", "minimum": 1},
                    "quote": text,
                },
                ["executor", "memoryId", "revision", "quote"],
            ),
            "workspacePreference": object_schema(
                {
                    "memoryId": text,
                    "revision": {"type": "integer", "minimum": 1},
                    "quote": text,
                    "base": text,
                    "remote": text,
                },
                ["memoryId", "revision", "quote"],
            ),
            "requiredCapabilities": {
                "type": "array",
                "maxItems": 24,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1, "maxLength": 160},
            },
        },
        ["explicitExecutor", "complexity", "complexityBasis", "routingExplanation"],
    )


def public_routing(decision):
    return {
        key: decision[key]
        for key in (
            "version",
            "policyVersion",
            "action",
            "executor",
            "complexity",
            "complexityBasis",
            "routingExplanation",
            "reasonCode",
            "capabilityVerification",
        )
        if key in decision
    }


class TaskRouter:
    def __init__(self, database, targets, settings, memory):
        self.db, self.targets, self.settings, self.memory = database, targets, settings, memory

    async def decide(self, args, binding):
        assessment = args["routing"]
        if not assessment["routingExplanation"].strip() or not all(
            str(v).strip() for v in assessment["complexityBasis"].values()
        ):
            raise DomainError("ROUTING_EXPLANATION_REQUIRED")
        key = "routing:" + binding["turnId"] + ":" + binding["toolCallId"]

        def source(db):
            turn = row(db, "SELECT * FROM turns WHERE id=?", (binding["turnId"],))
            origin = row(
                db,
                "SELECT m.* FROM messages m JOIN conversations c ON c.id=m.conversation_id "
                "WHERE m.id=? AND m.conversation_id=? AND c.owner_id=? AND m.role='user' "
                "AND m.deleted_ms IS NULL AND c.deleted_ms IS NULL",
                (binding["originMessageId"], binding["conversation"], binding["owner"]),
            )
            if not turn or not origin or turn["conversation_id"] != binding["conversation"]:
                raise DomainError("ROUTING_SOURCE_REQUIRED")
            assert_context_admitted(db, dict(turn, owner_id=binding["owner"]))
            if turn["state"] != "running":
                raise DomainError("TASK_TURN_INACTIVE", 409)
            prior = row(db, "SELECT payload_json FROM events WHERE event_key=?", (key,))
            if prior:
                value = json.loads(prior["payload_json"])
                if value["request"] != args:
                    raise DomainError("ROUTING_KEY_CONFLICT", 409)
                return origin, value["decision"]
            return origin, None

        origin, previous = await self.db.call(source)
        if previous:
            return previous
        explicit = assessment.get("explicitExecutor")
        if assessment.get("userQuote") and not explicit:
            raise DomainError("ROUTING_EXECUTOR_INTENT_REQUIRED")
        if explicit and (
            not assessment.get("userQuote", "").strip()
            or assessment["userQuote"] not in json.loads(origin["content_json"]).get("text", "")
        ):
            raise DomainError("ROUTING_EXPLICIT_SOURCE_REQUIRED")
        target = dict(args.get("target") or {"kind": "new_session"})
        workflow = await workspace_preference(
            self.memory, assessment.get("workspacePreference"), binding, target
        )
        if workflow:
            for name in ("base", "remote"):
                if name in workflow["values"]:
                    target.setdefault(name, workflow["values"][name])
        if target["kind"] == "project" and not target.get("projectId"):
            raise DomainError("CODING_PROJECT_ID_REQUIRED")
        if target["kind"] == "session" and not target.get("sessionId"):
            raise DomainError("CODING_SESSION_ID_REQUIRED")
        decision = {
            "version": 1,
            "policyVersion": "complexity-v3",
            "sourceMessageId": origin["id"],
            "complexity": assessment["complexity"],
            "complexityBasis": assessment["complexityBasis"],
            "routingExplanation": assessment["routingExplanation"],
            "targetRef": target,
            "metadataRefs": [],
            **({"workflowPreference": workflow} if workflow else {}),
            "capabilityVerification": "not_verified",
            "requiredCapabilities": assessment.get("requiredCapabilities", []),
        }
        if target["kind"] == "session":
            identity = await self.targets.resolve("session", target["sessionId"])
            actual = identity.get("executor")
            if explicit and actual != explicit:
                raise DomainError(
                    "ROUTING_SESSION_EXECUTOR_CONFLICT"
                    if actual
                    else "ROUTING_SESSION_EXECUTOR_UNKNOWN"
                )
            if args.get("fromMessageId"):
                raise DomainError("ROUTING_FORK_UNSUPPORTED")
            decision.update(
                action="send", executor=actual or "unknown", reasonCode="existing_session"
            )
            decision["targetRef"] = identity
        else:
            catalog = None
            commands = [
                value[4:]
                for value in assessment.get("requiredCapabilities", [])
                if value.startswith("cli:")
            ]
            if commands:
                catalog = await self.targets.executors(commands)
                observed = catalog.get("commandAvailability", {})
                if any(observed.get(name) is not True for name in commands):
                    raise DomainError("ROUTING_CAPABILITY_UNAVAILABLE")
                decision["capabilityVerification"] = "node_commands_observed"
                decision["metadataRefs"].append(catalog)
            project = None
            if target["kind"] == "project":
                project = await self.targets.resolve("project", target["projectId"])
                decision["metadataRefs"].append(project)
            preference = (
                await self._preference(assessment.get("preference"), binding, target)
                if not explicit and assessment["complexity"] == "complex"
                else None
            )
            if explicit:
                selected, reason = explicit, "explicit_executor"
            elif assessment["complexity"] == "bounded":
                selected, reason = "native", "bounded_native"
            else:
                catalog = catalog or await self.targets.executors()
                available = {
                    item["kind"]
                    for item in catalog["candidates"]
                    if item["installed"] is True
                    and item["tracked"] is True
                    and item["kind"] in EXECUTORS - {"native"}
                }
                ranked = [
                    (project.get("defaultExecutor") if project else None, "project_default"),
                    (preference, "user_preference"),
                    (self.settings.professional_executor, "node_default"),
                    (args.get("executor"), "complex_professional"),
                    (catalog.get("defaultExecutor"), "complex_professional"),
                ]
                selected, reason = next(
                    ((kind, why) for kind, why in ranked if kind in available), (None, None)
                )
                if not selected and len(available) == 1:
                    selected, reason = next(iter(available)), "complex_professional"
                if not selected:
                    raise DomainError("ROUTING_PROFESSIONAL_UNAVAILABLE")
                if catalog not in decision["metadataRefs"]:
                    decision["metadataRefs"].append(catalog)
            if selected != "native":
                if explicit:
                    catalog = catalog or await self.targets.executors()
                    if not any(
                        c["kind"] == selected and c["installed"] and c["tracked"]
                        for c in catalog["candidates"]
                    ):
                        raise DomainError("ROUTING_EXPLICIT_UNAVAILABLE")
                    decision["metadataRefs"].append(catalog)
                if args.get("fromMessageId"):
                    raise DomainError("ROUTING_FORK_UNSUPPORTED")
                if target.get("resourceOnly"):
                    raise DomainError("ROUTING_PROFILE_CONFLICT")
                if target["kind"] == "new_session" and not (
                    target.get("directory") or self.settings.coding_directory
                ):
                    raise DomainError("ROUTING_DIRECTORY_REQUIRED")
            decision.update(action="new_task", executor=selected, reasonCode=reason)

        if args.get("executor") and args["executor"] != decision["executor"]:
            raise DomainError("ROUTING_EXECUTOR_CONFLICT", 409)

        def persist(db):
            # A second admission closes the gap while CLI metadata was in flight.
            source(db)
            if workflow and not row(
                db,
                "SELECT id FROM memory_records WHERE id=? AND owner_id=? AND state='active' AND revision=?",
                (workflow["memoryId"], binding["owner"], workflow["revision"]),
            ):
                raise DomainError("WORKFLOW_PREFERENCE_SOURCE_INVALID", 409)
            old = row(db, "SELECT payload_json FROM events WHERE event_key=?", (key,))
            if old:
                return json.loads(old["payload_json"])["decision"]
            event(
                db,
                binding["conversation"],
                "routing.decided",
                {"request": args, "decision": decision},
                key=key,
                turn_id=binding["turnId"],
                message_id=binding["assistantMessageId"],
            )
            return decision

        return await self.db.call(persist, write=True)

    async def _preference(self, preference, binding, target):
        if not preference:
            return None
        memory = await self.memory.get(binding["owner"], preference["memoryId"])
        if (
            memory["kind"] != "preference"
            or memory["revision"] != preference["revision"]
            or preference["quote"] not in memory["body"]
            or memory.get("conversation_id") not in {None, binding["conversation"]}
            or memory.get("project_id") not in {None, target.get("projectId")}
            or memory.get("task_id") not in {None, binding.get("taskId")}
        ):
            raise DomainError("ROUTING_PREFERENCE_SOURCE_INVALID")
        return preference["executor"]
