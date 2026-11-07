"""Bind project Main reads to its registered directory without granting shell access."""

from roami_agent.conversation.project_okr import bound_project
from roami_agent.protocol.errors import DomainError


class ProjectFileScope:
    def __init__(self, database, targets, coordination):
        self.db, self.targets, self.coordination = database, targets, coordination

    async def project(self, binding):
        try:
            return await bound_project(self.db, binding)
        except DomainError as exc:
            if exc.code != "PROJECT_OKR_CONTEXT_REQUIRED":
                raise
            return None

    async def admit(self, tool, args, binding, *, after=False):
        args, binding = await self.coordination.admit(tool, args, binding, after=after)
        if (
            tool.name != "file_read"
            or binding.get("role") != "main"
            or binding.get("taskId")
            or binding.get("executionRunId")
            or not binding.get("owner")
            or not binding.get("conversation")
        ):
            return args, binding
        previous = binding.get("projectFileRead")
        if binding.get("workspace") and previous is None:
            return args, binding
        pid = await self.project(binding)
        if pid is None:
            if previous is not None:
                raise DomainError("PROJECT_FILE_SCOPE_CHANGED", 409)
            return args, binding
        workspace = await self.targets.project_workspace(pid)
        if await self.project(binding) != pid:
            raise DomainError("PROJECT_FILE_SCOPE_CHANGED", 409)
        # The second admission and post-read check must retain the original scope.
        if previous is not None and (
            previous != workspace or binding.get("workspace") != workspace
        ):
            raise DomainError("PROJECT_FILE_SCOPE_CHANGED", 409)
        return args, {**binding, "workspace": workspace, "projectFileRead": workspace}
