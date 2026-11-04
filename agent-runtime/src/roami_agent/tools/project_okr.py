"""Scoped OKR tools for the on-demand goal discussion, without a persistent swarm."""

from roami_agent.conversation.project_okr import bound_project, operation
from roami_agent.protocol.tools import Tool, object_schema


def register_project_okr_tools(registry, database, settings):
    async def context(args, binding):
        pid = await bound_project(database, binding)
        workspace = await operation(settings, pid, "show")
        return {**(workspace or {}), "projectId": pid, "saved": workspace is not None}

    async def update(args, binding):
        pid = await bound_project(database, binding)
        return await operation(settings, pid, args["operation"], args["payload"])

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
            "Apply a user-confirmed OKR change only to this goal conversation's bound project. First read project_okr_context; use its revision and the existing validated project operation JSON. Save definitions, collect registered sources, record real observations, review, sync staged definitions or update memory with expectedSha256. Conflicts require rereading. No shell, paths, credentials, model settings or public posting.",
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
