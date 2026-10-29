"""Immutable evidence validation and the existing blind model input format."""

import base64
import hashlib
import json

from roami_agent.improvement.domain.contracts import digest, require


def review_input(pack, renderer_image, *, expected_hash=None):
    require(isinstance(pack, dict), "RSI_ARTIFACT_EVIDENCE_CHANGED")
    require(
        pack.get("content_hash") == digest({k: v for k, v in pack.items() if k != "content_hash"})
        and (expected_hash is None or pack["content_hash"] == expected_hash),
        "RSI_ARTIFACT_EVIDENCE_CHANGED",
    )
    require(pack.get("renderer_image") == renderer_image, "RSI_ARTIFACT_RENDERER_CHANGED")
    labels = {v["label"] for v in pack["images"] + pack["texts"]} | {
        v["file"] for v in pack["artifacts"]
    }
    text = {k: v for k, v in pack.items() if k != "images"}
    text["allowed_labels"] = sorted(labels)
    content = [{"type": "text", "text": json.dumps(text, ensure_ascii=False)}]
    for item in pack["images"]:
        raw = base64.b64decode(item["data"], validate=True)
        require(hashlib.sha256(raw).hexdigest() == item["sha256"], "RSI_ARTIFACT_EVIDENCE_CHANGED")
        content.extend(
            [
                {"type": "text", "text": item["label"]},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:" + item["mime"] + ";base64," + item["data"]},
                },
            ]
        )
    return labels, content
