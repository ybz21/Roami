"""Attach bounded user images at the provider boundary, never in transcript JSON."""

import asyncio
import base64
import json

from roami_agent.context.image_preparation import prepare_image_bundle
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.image_limits import MAX_CONTEXT_IMAGES, ImageLimits
from roami_agent.storage.database import rows


class ChatImages:
    def __init__(self, database, artifacts, settings):
        self.db, self.artifacts, self.settings = database, artifacts, settings

    async def attach(self, turn, plan, prompt):
        if turn.get("executionRunId") or not plan.get("sourceMessageIds"):
            return plan, prompt
        sources = plan["sourceMessageIds"][-32:]
        items = await self.db.call(
            lambda db: rows(
                db,
                "SELECT * FROM artifacts WHERE owner_id=? AND deleted_ms IS NULL AND mime_type IN ('image/png','image/jpeg','image/webp') AND message_id IN (SELECT value FROM json_each(?)) AND json_extract(metadata_json,'$.source')='chat-upload' AND NOT EXISTS(SELECT 1 FROM memory_tombstones t WHERE t.owner_id=artifacts.owner_id AND t.source_fingerprint=artifacts.sha256) ORDER BY rowid DESC LIMIT ?",
                (turn["owner_id"], json.dumps(sources), MAX_CONTEXT_IMAGES),
            )
        )
        if not items:
            return plan, prompt
        if self.settings.route("main").capabilities.get("images") is not True:
            return plan, [
                *prompt,
                {
                    "role": "user",
                    "content": "The attached image contents are unavailable: this Main model is not configured for image input. Explain the limitation if image understanding is needed; never claim to have inspected these images.",
                },
            ]
        readable = []
        for index, item in enumerate(items):
            try:
                reference, body = await self.artifacts.read(turn["owner_id"], item["id"])
                readable.append((index, reference, body))
            except (DomainError, OSError, ValueError):
                continue
        prepared = await asyncio.to_thread(
            prepare_image_bundle,
            [value[2] for value in readable],
            ImageLimits.configured(self.settings.route("main").image_limits),
        )
        images = {readable[index][0]: (readable[index][1], image) for index, image in prepared}
        parts, evidence = [], []
        for index in reversed(range(len(items))):
            item = items[index]
            if index in images:
                reference, image = images[index]
                parts.extend(
                    [
                        {"type": "text", "text": "User attachment: " + item["name"]},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:"
                                + image["mimeType"]
                                + ";base64,"
                                + base64.b64encode(image["body"]).decode()
                            },
                        },
                    ]
                )
                evidence.append(
                    {
                        "artifactId": item["id"],
                        "sha256": reference["sha256"],
                        "width": image["width"],
                        "height": image["height"],
                        "originalWidth": image["originalWidth"],
                        "originalHeight": image["originalHeight"],
                        "mimeType": image["mimeType"],
                        "optimized": image["optimized"],
                    }
                )
            else:
                parts.append(
                    {
                        "type": "text",
                        "text": "Attachment image unavailable or exceeds the combined image payload budget: "
                        + item["name"],
                    }
                )
        return {**plan, "imageEvidence": evidence}, [*prompt, {"role": "user", "content": parts}]
