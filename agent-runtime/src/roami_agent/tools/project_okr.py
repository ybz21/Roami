"""Project-scoped OKR tools for the goal's persistent coordinator."""

from roami_agent.conversation.project_main import project_team
from roami_agent.conversation.project_okr import bound_project, operation
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema


def register_project_okr_tools(registry, database, settings):
    from roami_agent.tools.project_memory_edit import register_project_memory_edit

    register_project_memory_edit(registry, database, settings)
    from roami_agent.tools.project_review import checked_review, register_project_review

    register_project_review(registry, database, settings)

    async def context(args, binding):
        pid = await bound_project(database, binding)
        workspace = await operation(settings, pid, "show")
        return {**(workspace or {}), "projectId": pid, "saved": workspace is not None}

    async def update(args, binding):
        pid = await bound_project(database, binding)
        if args["operation"] == "review":
            args = {**args, "payload": checked_review(args["payload"])}
        if args["operation"] == "save" and args["payload"].get("swarm"):
            team = await database.call(
                lambda db: project_team(db, binding["owner"], pid, args["payload"]["swarm"])
            )
            if team["conversation_id"] != binding["conversation"]:
                raise DomainError("PROJECT_OKR_TEAM_CONFLICT", 409)
        return await operation(settings, pid, args["operation"], args["payload"])

    async def append_memory(args, binding):
        pid = await bound_project(database, binding)
        return await operation(
            settings,
            pid,
            "memory",
            {
                "mode": "append",
                "content": args["content"],
                "expectedSha256": args["expectedSha256"],
            },
        )

    registry.add(
        Tool(
            "project_okr_memory_append",
            "Append verified lasting knowledge to this project's team memory, preserving existing text. Read project_okr_context first and use projectFiles.teamMemorySha256 as expectedSha256. Supply only the new knowledge as content. Conflicts require rereading; never probe live writes with placeholder/test content. The host retains prior bytes in memory/history for recovery.",
            object_schema(
                {
                    "content": {"type": "string", "minLength": 1, "maxLength": 65536},
                    "expectedSha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                },
                ["content", "expectedSha256"],
            ),
            append_memory,
            effect="write",
            main=True,
        )
    )

    registry.add(
        Tool(
            "project_okr_context",
            "Read this goal conversation's bound registered project OKR: current revision, definitions, dashboard, dated observations/reviews and project instructions/memory. A new goal returns saved=false without invented metrics. Project selection is fixed by the host and cannot be supplied by the model.",
            object_schema({}),
            context,
            effect="read",
            main=True,
        )
    )
    registry.add(
        Tool(
            "project_okr_update",
            "Apply a user-confirmed OKR change only to this goal conversation's bound project. First read project_okr_context; use its revision and the existing validated project operation JSON. Save objective, dashboard, Connector bindings and desired team roles (team.schemaVersion=1, roles with id/name/executor/duty); saving roles does not register or dispatch members. Collect registered sources, record real observations, review or sync staged definitions. For new team knowledge use project_okr_memory_append; memory replacement requires the full intended document and its current expectedSha256. Never discover schemas by probing live writes. For whole-project creation discover okr-development. Conflicts require rereading. No shell, paths, credentials, model settings or public posting.",
            object_schema(
                {
                    "operation": {
                        "type": "string",
                        "enum": ["save", "collect", "record", "review", "sync", "memory"],
                    },
                    "payload": {"type": "object"},
                },
                ["operation", "payload"],
            ),
            update,
            effect="write",
            main=True,
        )
    )
