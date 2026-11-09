"""Main-only frozen content and independent review; no network publishing capability."""

from roami_agent.dispatch.publication_manifest import PublicationManifest
from roami_agent.dispatch.publication_review import PublicationReview
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.publication.releases import PublicationReleases
from roami_agent.storage.publication_reviews import current_version
from roami_agent.storage.publication_versions import create_item, freeze_version


def register_publication_tools(registry, database, artifacts, reviewer):
    async def prepare(args, binding):
        scope = {
            key: args[key]
            for key in (
                "projectId",
                "swarmId",
                "delegationId",
                "memberId",
                "taskId",
                "revision",
                "runId",
            )
        }
        content = args["content"]
        if not isinstance(content, dict) or any(
            not isinstance(value, (str, list)) for value in content.values()
        ):
            raise DomainError("INVALID_PUBLICATION_CONTENT")
        paths = []
        for value in content.values():
            selected = value if isinstance(value, list) else [value]
            if any(not isinstance(path, str) for path in selected):
                raise DomainError("INVALID_PUBLICATION_CONTENT")
            paths.extend(selected)
        paths = list(dict.fromkeys(paths))
        item = await database.call(
            lambda db: create_item(db, binding, scope, args["businessKey"], args["channel"]),
            write=True,
        )
        snapshot = await PublicationManifest(database, artifacts).snapshot(
            binding, scope, args["manifest"], paths
        )
        by_path = {value["path"]: value for value in snapshot["artifacts"]}
        mapped = {
            key: [by_path[path]["id"] for path in value]
            if isinstance(value, list)
            else by_path[value]["id"]
            for key, value in content.items()
        }
        version = await database.call(
            lambda db: freeze_version(
                db,
                binding,
                item["id"],
                scope,
                list(by_path.values()),
                mapped,
                account_identity=args.get("accountIdentity"),
            ),
            write=True,
        )
        return {**version, "itemId": item["id"], "artifacts": snapshot["artifacts"]}

    async def review(args, binding):
        _, manifest = await database.call(
            lambda db: current_version(db, binding, args["versionId"])
        )
        if manifest["author"]["swarmId"] != args["swarmId"]:
            raise DomainError("PUBLICATION_PROJECT_SCOPE_CONFLICT", 403)
        return await PublicationReview(database, artifacts, reviewer()).decide(
            binding, args["versionId"], args["decision"], args["feedback"]
        )

    async def release(args, binding):
        return await PublicationReleases(database, artifacts, reviewer()).prepare(
            binding, args, args["versionId"], args["reviewId"], args["channel"], args["accountId"]
        )

    string = {"type": "string", "minLength": 1}
    scope = {
        key: string
        for key in ("projectId", "swarmId", "delegationId", "memberId", "taskId", "runId")
    }
    scope["revision"] = {"type": "integer", "minimum": 1}
    reference = object_schema(
        {
            "id": {
                **string,
                "description": "Retained manifest artifact ID from the host result, never a filename or filesystem path.",
            },
            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
        ["id", "sha256"],
    )
    content = object_schema(
        {
            **{
                key: {
                    **string,
                    "description": "Exact relative file path in manifest.files[].path, not literal content or a project-root path. For body use e.g. 01-post.en.txt; the host reads and freezes that file.",
                }
                for key in ("body", "title", "tags", "video", "audio", "subtitles")
            },
            "images": {
                "type": "array",
                "description": "Exact relative image paths from manifest.files[].path, e.g. 01-card.png; no project-root prefixes.",
                "minItems": 1,
                "maxItems": 20,
                "uniqueItems": True,
                "items": string,
            },
            "imageAlts": {
                "type": "array",
                "description": "Exact relative ALT text file paths from manifest.files[].path, paired by position with images. Supply one text artifact per image; these bytes are frozen and must be fully read before independent approval. Never put literal ALT text here.",
                "minItems": 1,
                "maxItems": 20,
                "items": string,
            },
        },
        ["body"],
    )
    registry.add(
        Tool(
            "swarm_publication_prepare",
            "Freeze selected files from an original member's current completed run and retained manifest. The manifest JSON requires a nested identity object {taskId, revision: integer, runId}, not flat top-level identity fields; Each files entry directly carries taskId/revision/runId plus path/bytes/sha256; a nested per-file identity alone is insufficient. File paths are relative to the manifest file's own directory, not the project or run root. content maps body/title/tags/images/video/audio/subtitles to these exact paths. Use one stable businessKey per real planned publication through revisions and retries. First independently verify the artifact task with swarm_verify. Returns immutable artifacts to read before review; this does not approve or publish anything.",
            object_schema(
                {
                    **scope,
                    "businessKey": string,
                    "channel": {"type": "string", "enum": ["x", "bilibili"]},
                    "manifest": reference,
                    "content": content,
                    "accountIdentity": {
                        **string,
                        "description": "Verified numeric platform account ID as a decimal string, never an @handle, display name or URL. Historical identity does not establish current login or posting access.",
                    },
                },
                [*scope, "businessKey", "channel", "manifest", "content"],
            ),
            prepare,
            main=True,
            effect="write",
        )
    )
    registry.add(
        Tool(
            "swarm_publication_review",
            "Independently approve or reject an exact frozen version. Approval requires full current-turn artifact text reads in the actual Main model input and image file reads with actual image input evidence; execution summaries and author claims cannot substitute. Video/audio approval is unavailable until linked media review is supported. State feedback briefly. This records an immutable host review, never permission or proof of publication.",
            object_schema(
                {
                    "swarmId": string,
                    "versionId": string,
                    "decision": {"type": "string", "enum": ["approved", "rejected"]},
                    "feedback": {"type": "string", "minLength": 1, "maxLength": 8000},
                },
                ["swarmId", "versionId", "decision", "feedback"],
            ),
            review,
            main=True,
            effect="write",
        )
    )
    registry.add(
        Tool(
            "swarm_publication_release",
            "Create an immutable handoff of an independently approved frozen version to its original member. Rechecks the current user goal, automatic-mode proof, account and retained assets. Does not send, grant resource access or prove publication. The original worker still needs current host admission and a durable single-submit intent.",
            object_schema(
                {
                    **{
                        key: string
                        for key in ("projectId", "swarmId", "delegationId", "memberId", "taskId")
                    },
                    "versionId": string,
                    "reviewId": string,
                    "channel": {"type": "string", "enum": ["x", "bilibili"]},
                    "accountId": {"type": "string", "pattern": "^[1-9][0-9]{0,29}$"},
                },
                [
                    "projectId",
                    "swarmId",
                    "delegationId",
                    "memberId",
                    "taskId",
                    "versionId",
                    "reviewId",
                    "channel",
                    "accountId",
                ],
            ),
            release,
            main=True,
            effect="write",
        )
    )
