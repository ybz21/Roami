"""Capture immutable images from the reading role's admitted file scope."""

import asyncio
import hashlib
import io
from pathlib import PurePath

from PIL import Image

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.image_limits import MAX_PIXELS
from roami_agent.storage.database import row


class WorkspaceImageReadError(DomainError):
    def __init__(self, error, path):
        super().__init__(error.code, error.status)
        self.path = path


class WorkspaceImageReads:
    max_bytes = 32 * 1024 * 1024
    suffixes = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})

    def __init__(self, files, artifacts):
        self.files, self.artifacts = files, artifacts

    @staticmethod
    def inspect(body):
        try:
            with Image.open(io.BytesIO(body)) as image:
                if (
                    image.format not in {"PNG", "JPEG", "WEBP"}
                    or image.width * image.height > MAX_PIXELS
                    or getattr(image, "is_animated", False)
                ):
                    raise ValueError("VISION_IMAGE_INVALID")
                image.load()
                return Image.MIME[image.format], image.width, image.height
        except Image.DecompressionBombError:
            raise ValueError("VISION_IMAGE_INVALID") from None

    async def read(self, args, binding):
        role = binding.get("role")
        worker = role == "worker" and all(
            binding.get(key) for key in ("taskId", "runId", "workspace")
        )
        main = role == "main" and not binding.get("taskId") and not binding.get("runId")
        visual = (
            PurePath(args["path"]).suffix.lower() in self.suffixes
            and (worker or main)
            and all(
                binding.get(key) for key in ("owner", "turnId", "assistantMessageId", "toolCallId")
            )
            and self.files.settings.route(role).capabilities.get("images") is True
        )
        if visual and worker:
            active = await self.artifacts.db.call(
                lambda db: row(
                    db,
                    "SELECT 1 FROM task_attempts r JOIN tasks t ON t.id=r.task_id "
                    "JOIN turns u ON u.id=? AND u.branch_id=r.native_branch_id AND u.state='running' "
                    "WHERE r.id=? AND t.id=? AND t.owner_id=? AND r.state='running' "
                    "AND t.state='running' AND r.task_revision=t.revision",
                    (
                        binding.get("turnId"),
                        binding.get("runId"),
                        binding.get("taskId"),
                        binding["owner"],
                    ),
                )
            )
            if not active:
                raise DomainError("NATIVE_EXECUTION_CONTEXT_MISMATCH")
        elif visual:
            active = await self.artifacts.db.call(
                lambda db: row(
                    db,
                    "SELECT 1 FROM turns u JOIN conversations c ON c.id=u.conversation_id "
                    "JOIN messages m ON m.id=? AND m.turn_id=u.id "
                    "AND m.branch_id=u.branch_id AND m.conversation_id=u.conversation_id "
                    "WHERE u.id=? AND u.state='running' AND c.owner_id=? "
                    "AND NOT EXISTS(SELECT 1 FROM task_attempts r WHERE r.native_branch_id=u.branch_id)",
                    (binding["assistantMessageId"], binding["turnId"], binding["owner"]),
                )
            )
            if not active:
                raise DomainError("NATIVE_EXECUTION_CONTEXT_MISMATCH")
        if not visual:
            return await self.files.read(args, binding)
        root, components = self.files.location(args["path"], binding)
        path = str(root.joinpath(*components)) if main else "/".join(components)
        try:
            return await self._capture(args, binding, path)
        except DomainError as exc:
            raise WorkspaceImageReadError(exc, path) from exc

    async def _capture(self, args, binding, path):
        result = await self.files.read(args, binding)
        if args.get("offset", 0):
            return {
                **result,
                "fileImage": {"path": path, "unavailable": "VISION_IMAGE_UNAVAILABLE"},
            }
        maximum = min(self.max_bytes, self.artifacts.max_bytes or self.max_bytes)
        try:
            body = await self.files.snapshot(args["path"], binding, maximum=maximum)
            if hashlib.sha256(body).hexdigest() != result["sha256"]:
                raise DomainError("FILE_CHANGED", 409)
            mime, width, height = await asyncio.to_thread(self.inspect, body)
        except (OSError, ValueError):
            return {**result, "fileImage": {"path": path, "unavailable": "VISION_IMAGE_INVALID"}}
        except DomainError as exc:
            if exc.code != "FILE_TYPE_OR_SIZE_UNSUPPORTED":
                raise
            return {**result, "fileImage": {"path": path, "unavailable": "VISION_IMAGE_LIMIT"}}
        artifact = await self.artifacts.put(
            binding["owner"],
            body,
            mime_type=mime,
            task_id=binding.get("taskId"),
            message_id=binding["assistantMessageId"],
            name=PurePath(args["path"]).name[:180],
            metadata={
                "source": "workspace_image",
                "runId": binding.get("runId"),
                "readerRole": binding["role"],
                "turnId": binding["turnId"],
                "toolCallId": binding["toolCallId"],
                "sourceSha256": result["sha256"],
                "sourcePath": path,
            },
        )
        return {
            **result,
            "fileImage": {
                "artifactId": artifact["id"],
                "sha256": artifact["sha256"],
                "width": width,
                "height": height,
                "path": path,
            },
        }
