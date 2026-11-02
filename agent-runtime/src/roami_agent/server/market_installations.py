"""Install the exact marketplace option reviewed by a CLI or Agent caller."""

import asyncio
import copy
import secrets
import time

from roami_agent.protocol.errors import DomainError
from roami_agent.server.model_settings import ModelSettings


class MarketInstallations:
    def __init__(self, markets):
        self.markets = markets
        self.receipts = {}
        self.lock = asyncio.Lock()

    async def prepare(self, owner, payload):
        source = self.markets.source(
            owner, payload.get("source") if isinstance(payload, dict) else None
        )
        preview = await self.markets.preview(owner, payload)
        if source != self.markets.source(owner, payload["source"]):
            raise DomainError("MARKET_SOURCE_CHANGED", 409)
        self.receipts = {
            key: value for key, value in self.receipts.items() if value["until"] > time.monotonic()
        }
        if len(self.receipts) >= 32:
            self.receipts.pop(next(iter(self.receipts)))
        identifier = secrets.token_urlsafe(24)
        self.receipts[identifier] = {
            "until": time.monotonic() + 600,
            "source": source,
            "preview": preview,
            "installed": {},
        }
        options = []
        for index, option in enumerate(preview["options"]):
            entry = option["entry"]
            summary = {
                key: copy.deepcopy(value)
                for key, value in entry.items()
                if key not in {"files", "text"}
            }
            if "text" in entry:
                summary.update(text=entry["text"][:8000], textTruncated=len(entry["text"]) > 8000)
            options.append(
                {
                    "option": index,
                    "label": option["label"],
                    "entry": summary,
                    "files": sorted(entry.get("files", {})),
                }
            )
        return {
            "previewId": identifier,
            "expiresAt": int(time.time() * 1000) + 600_000,
            "kind": preview["kind"],
            "options": options,
        }

    async def install(self, owner, payload):
        ModelSettings.owner(owner)
        if (
            not isinstance(payload, dict)
            or set(payload) - {"previewId", "option", "name"}
            or not isinstance(payload.get("previewId"), str)
            or len(payload["previewId"]) > 64
            or type(payload.get("option")) is not int
            or ("name" in payload and not isinstance(payload["name"], str))
        ):
            raise DomainError("INVALID_MARKET_INSTALL")
        async with self.lock, self.markets.lock:
            receipt = self.receipts.get(payload["previewId"])
            if not receipt or receipt["until"] <= time.monotonic():
                raise DomainError("MARKET_PREVIEW_EXPIRED", 409)
            source = self.markets.source(owner, receipt["source"]["id"])
            if source != receipt["source"]:
                raise DomainError("MARKET_SOURCE_CHANGED", 409)
            preview = receipt["preview"]
            index = payload["option"]
            if not 0 <= index < len(preview["options"]):
                raise DomainError("INVALID_MARKET_INSTALL")
            entry = copy.deepcopy(preview["options"][index]["entry"])
            entry["name"] = payload.get("name", entry["name"])
            entry = self.markets.runtime.capability_imports.validate(preview["kind"], entry)
            key = (index, entry["name"])
            if key in receipt["installed"]:
                saved = self.markets.runtime.capability_imports.saved[preview["kind"]].get(
                    entry["name"]
                )
                if saved != entry:
                    raise DomainError("MARKET_INSTALL_CHANGED", 409)
                return copy.deepcopy(receipt["installed"][key])
            await self.markets.runtime.capability_imports.save(owner, preview["kind"], entry)
            result = {
                "kind": preview["kind"],
                "name": entry["name"],
                "origin": entry["origin"],
                "state": "registered" if preview["kind"] == "mcp" else "installed",
            }
            if preview["kind"] == "skills":
                result["location"] = "skill://" + entry["name"]
            if preview["kind"] == "mcp":
                result["connected"] = False
            receipt["installed"][key] = result
            return copy.deepcopy(result)
