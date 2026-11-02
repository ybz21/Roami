"""Persistent private working directories for native tasks without a user-selected target."""

import asyncio
import os
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity


def automatic_task_directory(target):
    return (
        target.get("kind") == "new_session"
        and target.get("nodeId", "local") == "local"
        and not target.get("resourceOnly")
        and not any(
            target.get(key) for key in ("directory", "workspaceId", "projectId", "sessionId")
        )
    )


async def prepare_task_directory(data_root, task_id):
    def prepare():
        if not task_id or Path(task_id).name != task_id or task_id in {".", ".."}:
            raise DomainError("TASK_DIRECTORY_UNAVAILABLE")
        root = Path(data_root) / "agents" / "task-directories"
        try:
            root.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            root.mkdir(mode=0o700, exist_ok=True)
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                try:
                    os.mkdir(task_id, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(
                    task_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                try:
                    probe = ".write-probe-" + identity()
                    file = os.open(
                        probe,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=child,
                    )
                    os.close(file)
                    os.unlink(probe, dir_fd=child)
                finally:
                    os.close(child)
            finally:
                os.close(descriptor)
        except OSError:
            raise DomainError("TASK_DIRECTORY_UNAVAILABLE", 503) from None
        return {
            "workspaceId": "native-task:" + task_id,
            "directory": str(root / task_id),
            "taskDirectory": True,
        }

    return await asyncio.to_thread(prepare)
