"""JSON catalog endpoints used by skills.sh and its authenticated API."""

import base64
import hashlib
import json
import os
import re
from urllib.parse import quote

from roami_agent.protocol.errors import DomainError
from roami_agent.server.skill_package import MAX_PACKAGE_BYTES, package_files

VIEWS = {"all-time", "trending", "hot"}
IDENTIFIER = re.compile(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.:-]+")


def authorization(source):
    # Never forward a node credential to a user-configured mirror.
    if source["url"] in {"https://skills.sh", "https://www.skills.sh"}:
        token = os.environ.get("VERCEL_OIDC_TOKEN", "").strip()
        if token:
            return {"Authorization": "Bearer " + token}
    return None


def listing(source, item):
    identifier = item.get("id") or item["source"] + "/" + item.get("skillId", item.get("slug", ""))
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        return None
    return {
        "id": identifier,
        "name": item["name"],
        "description": item.get("description") or item.get("source", ""),
        "url": source["url"] + "/" + quote(identifier, safe="/"),
        "version": "",
        **({"installs": item["installs"]} if type(item.get("installs")) is int else {}),
    }


async def search(source, query, cursor, view, fetch):
    headers = authorization(source)
    base = source["url"]
    page = int(cursor or "0")
    if headers:
        path = "/api/v1/skills/search" if query else "/api/v1/skills"
        params = (
            {"q": query, "limit": 20} if query else {"view": view, "page": page, "per_page": 20}
        )
        data = await fetch(base + path, params=params, headers=headers)
        rows = data["data"]
        more = not query and data.get("pagination", {}).get("hasMore", False)
    elif query:
        data = await fetch(base + "/api/search", params={"q": query, "limit": 20})
        rows, more = data["skills"], False
    else:
        data = await fetch(base + f"/api/skills/{view}/{page}")
        rows, more = data["skills"], data.get("hasMore", False)
    items = [row for item in rows[:200] if (row := listing(source, item)) is not None]
    return {"items": items, "nextCursor": str(page + 1) if more else ""}


async def snapshot(source, identifier, fetch):
    headers = authorization(source)
    if not headers:
        return None
    if not IDENTIFIER.fullmatch(identifier):
        raise DomainError("MARKET_ITEM_NOT_FOUND", 404)
    data = await fetch(
        source["url"] + "/api/v1/skills/" + quote(identifier, safe="/"), headers=headers
    )
    if data.get("id") != identifier:
        raise DomainError("MARKET_UNAVAILABLE", 502)
    if data.get("files") is None:
        return None
    files = {}
    for item in data["files"]:
        if item["path"] in files or not isinstance(item["contents"], str):
            raise DomainError("INVALID_SKILL_PACKAGE")
        files[item["path"]] = base64.b64encode(item["contents"].encode()).decode()
    if len(json.dumps(files)) > MAX_PACKAGE_BYTES * 2:
        raise DomainError("MARKET_PACKAGE_TOO_LARGE", 413)
    decoded = package_files({"files": files})
    if "SKILL.md" not in decoded:
        raise DomainError("INVALID_SKILL_PACKAGE")
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return decoded["SKILL.md"].decode(), files, "sha256:" + digest
