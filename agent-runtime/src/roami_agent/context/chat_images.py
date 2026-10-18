"""Attach bounded user images at the provider boundary, never in transcript JSON."""

import asyncio
import base64
import io
import json

from PIL import Image

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import rows


class ChatImages:
    def __init__(self, database, artifacts, settings):
        self.db, self.artifacts, self.settings = database, artifacts, settings

    @staticmethod
    def rendered(body):
        with Image.open(io.BytesIO(body)) as image:
            if image.width * image.height > 16_000_000:
                raise ValueError
            image.thumbnail((1600, 1600))
            output = io.BytesIO()
            image.convert("RGB").save(output, format="JPEG", quality=85)
            if output.tell() > 2 * 1024 * 1024:
                raise ValueError
            return output.getvalue(), image.width, image.height

    async def attach(self, turn, plan, prompt):
        if turn.get("executionRunId") or not plan.get("sourceMessageIds"):
            return plan, prompt
        sources = plan["sourceMessageIds"][-32:]
        items = await self.db.call(
            lambda db: rows(
                db,
                "SELECT * FROM artifacts WHERE owner_id=? AND deleted_ms IS NULL AND mime_type IN ('image/png','image/jpeg','image/webp') AND message_id IN (SELECT value FROM json_each(?)) AND json_extract(metadata_json,'$.source')='chat-upload' AND NOT EXISTS(SELECT 1 FROM memory_tombstones t WHERE t.owner_id=artifacts.owner_id AND t.source_fingerprint=artifacts.sha256) ORDER BY rowid DESC LIMIT 3",
                (turn["owner_id"], json.dumps(sources)),
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
        parts, evidence = [], []
        for item in reversed(items):
            try:
                reference, body = await self.artifacts.read(turn["owner_id"], item["id"])
                image, width, height = await asyncio.to_thread(self.rendered, body)
                parts.extend(
                    [
                        {"type": "text", "text": "User attachment: " + item["name"]},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/jpeg;base64," + base64.b64encode(image).decode()
                            },
                        },
                    ]
                )
                evidence.append(
                    {
                        "artifactId": item["id"],
                        "sha256": reference["sha256"],
                        "width": width,
                        "height": height,
                    }
                )
            except (DomainError, OSError, ValueError):
                parts.append(
                    {"type": "text", "text": "Attachment image unavailable: " + item["name"]}
                )
        return {**plan, "imageEvidence": evidence}, [*prompt, {"role": "user", "content": parts}]
