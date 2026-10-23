"""Read public capability catalogs and translate listings into reviewable registrations."""

import asyncio
import base64
import json
import re
from urllib.parse import quote, urlsplit

import httpx

from roami_agent.protocol.errors import DomainError
from roami_agent.server.skill_market_archive import download_archive
from roami_agent.server.skill_package import MAX_PACKAGE_BYTES

DEFAULT_SOURCES = [
    {
        "id": "skills-sh",
        "name": "skills.sh",
        "provider": "skills_sh",
        "url": "https://skills.sh",
        "enabled": True,
    },
    {
        "id": "mcp-registry",
        "name": "MCP Registry",
        "provider": "mcp_registry",
        "url": "https://registry.modelcontextprotocol.io",
        "enabled": True,
    },
    {
        "id": "npm",
        "name": "npm",
        "provider": "npm",
        "url": "https://registry.npmjs.org",
        "enabled": True,
    },
]
PROVIDER_KINDS = {"skills_sh": "skills", "mcp_registry": "mcp", "npm": "cli"}


def public_url(url):
    if not isinstance(url, str) or len(url) > 2000:
        raise DomainError("INVALID_MARKET_SOURCE")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise DomainError("INVALID_MARKET_SOURCE")
    return url.rstrip("/")


async def fetch(url, *, params=None, raw=False, maximum=None):
    try:
        async with (
            httpx.AsyncClient(
                timeout=20,
                follow_redirects=False,
                headers={"User-Agent": "Roami-Capability-Center", "Accept": "application/json"},
            ) as client,
            client.stream("GET", url, params=params) as response,
        ):
            if response.status_code == 429:
                raise DomainError("MARKET_RATE_LIMITED", 429)
            if response.status_code == 404:
                raise DomainError("MARKET_ITEM_NOT_FOUND", 404)
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > (maximum or (MAX_PACKAGE_BYTES if raw else 2_000_000)):
                    raise DomainError("MARKET_PACKAGE_TOO_LARGE", 413)
            return bytes(body) if raw else json.loads(body)
    except (httpx.HTTPError, ValueError, TypeError):
        raise DomainError("MARKET_UNAVAILABLE", 502) from None


def local_name(name, limit=64):
    name = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-_")
    return (("cap-" if not name or not name[0].isalpha() else "") + name)[:limit]


async def search(source, query, cursor=""):
    base, provider = source["url"], source["provider"]
    rows, next_cursor = [], ""
    if provider == "skills_sh":
        data = await fetch(base + "/api/search", params={"q": query, "limit": 20})
        for item in data["skills"][:20]:
            rows.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "description": item.get("source", ""),
                    "url": base + "/" + quote(item["id"], safe="/"),
                    "version": "",
                }
            )
    elif provider == "mcp_registry":
        params = {"search": query, "limit": 20, "version": "latest"}
        if cursor:
            params["cursor"] = cursor
        data = await fetch(base + "/v0.1/servers", params=params)
        for item in data["servers"][:20]:
            status = (
                item.get("_meta", {})
                .get("io.modelcontextprotocol.registry/official", {})
                .get("status", "active")
            )
            if status != "active":
                continue
            server = item["server"]
            rows.append(
                {
                    "id": server["name"],
                    "name": server.get("title") or server["name"],
                    "description": server.get("description", ""),
                    "version": server["version"],
                    "url": base
                    + "/v0.1/servers/"
                    + quote(server["name"], safe="")
                    + "/versions/"
                    + quote(server["version"], safe=""),
                }
            )
        next_cursor = data.get("metadata", {}).get("nextCursor", "")
    else:
        offset = int(cursor or "0")
        data = await fetch(
            base + "/-/v1/search", params={"text": query, "size": 20, "from": offset}
        )
        for item in data["objects"][:20]:
            package = item["package"]
            rows.append(
                {
                    "id": package["name"],
                    "name": package["name"],
                    "description": package.get("description", ""),
                    "version": package["version"],
                    "url": "https://www.npmjs.com/package/" + quote(package["name"], safe="/@"),
                }
            )
        if offset + 20 < data.get("total", 0):
            next_cursor = str(offset + 20)
    return {"items": rows, "nextCursor": next_cursor}


async def skill_entry(identifier):
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.:-]+", identifier):
        raise DomainError("MARKET_ITEM_NOT_FOUND", 404)
    owner, repo, skill = identifier.split("/")

    async def archived():
        text, files, commit = await download_archive(owner, repo, skill, fetch)
        match = re.search(r"(?m)^description:\s*(.+)$", text)
        return {
            "name": local_name(skill),
            "description": match[1].strip("\"'") if match else skill,
            "text": text,
            "files": files,
        }, commit

    api = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        commit = (await fetch(api + "/commits/HEAD"))["sha"]
    except DomainError as exc:
        if exc.code not in {"MARKET_UNAVAILABLE", "MARKET_RATE_LIMITED"}:
            raise
        return await archived()
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise DomainError("MARKET_UNAVAILABLE", 502)
    tree = await fetch(api + "/git/trees/" + commit, params={"recursive": "1"})
    if tree.get("truncated"):
        raise DomainError("MARKET_PACKAGE_TOO_LARGE", 413)
    candidates = [
        item["path"]
        for item in tree["tree"]
        if item.get("type") == "blob"
        and (item["path"] == "SKILL.md" or item["path"].endswith("/SKILL.md"))
        and (item["path"] == "SKILL.md" or item["path"].split("/")[-2] == skill)
    ]
    if len(candidates) != 1:
        return await archived()
    prefix = candidates[0].removesuffix("SKILL.md")
    selected = [
        item
        for item in tree["tree"]
        if item["path"].startswith(prefix) and item.get("type") == "blob"
    ]
    # Preserve repository licensing when it lives outside the skill folder.
    selected += [
        item
        for item in tree["tree"]
        if prefix
        and item["path"] in {"LICENSE", "LICENSE.md", "LICENSE.txt"}
        and not any(row["path"] == prefix + item["path"] for row in selected)
    ]
    if (
        len(selected) > 100
        or sum(item.get("size", 0) for item in selected) > MAX_PACKAGE_BYTES
        or any(item.get("mode") not in {"100644", "100755"} for item in selected)
    ):
        raise DomainError("MARKET_PACKAGE_TOO_LARGE", 413)
    semaphore = asyncio.Semaphore(5)

    async def download(item):
        async with semaphore:
            path = item["path"]
            raw = await fetch(
                f"https://raw.githubusercontent.com/{owner}/{repo}/{commit}/"
                + quote(path, safe="/"),
                raw=True,
            )
            return path.removeprefix(prefix) if path.startswith(prefix) else path, raw

    contents = dict(await asyncio.gather(*(download(item) for item in selected)))
    if sum(map(len, contents.values())) > MAX_PACKAGE_BYTES:
        raise DomainError("MARKET_PACKAGE_TOO_LARGE", 413)
    try:
        text = contents["SKILL.md"].decode("utf-8")
    except (KeyError, UnicodeDecodeError):
        raise DomainError("INVALID_SKILL_PACKAGE") from None
    match = re.search(r"(?m)^description:\s*(.+)$", text)
    return {
        "name": local_name(skill),
        "description": match[1].strip("\"'") if match else skill,
        "text": text,
        "files": {name: base64.b64encode(raw).decode() for name, raw in contents.items()},
    }, commit


def mcp_options(server):
    options = []
    name = local_name(server["name"].split("/")[-1], 20)
    for remote in server.get("remotes", []):
        transport = {"streamable-http": "streamable_http", "sse": "sse"}.get(remote.get("type"))
        if not transport:
            continue
        config = {"transport": transport, "url": remote["url"]}
        for header in remote.get("headers", []):
            if header.get("isRequired") is False:
                continue
            if header["name"].lower() == "authorization" and header.get(
                "value", "Bearer "
            ).startswith("Bearer "):
                config["key_env"] = "MCP_" + name.upper().replace("-", "_") + "_TOKEN"
            else:
                config.setdefault("header_env", {})[header["name"]] = (
                    "MCP_" + re.sub(r"\W", "_", header["name"]).upper()
                )
        options.append({"label": transport, "entry": {"name": name, "config": config}})
    for package in server.get("packages", []):
        kind = package.get("registryType")
        identifier, version = package.get("identifier", ""), package.get("version", "")
        if kind == "npm":
            argv = ["npx", "--yes", identifier + ("@" + version if version else "")]
        elif kind == "pypi":
            argv = ["uvx", identifier + ("==" + version if version else "")]
        else:
            continue

        def arguments(values):
            result = []
            for arg in values:
                if arg.get("isRequired") is False and arg.get("value") is None:
                    continue
                if arg.get("name"):
                    result.append(arg["name"])
                if arg.get("value") is not None:
                    result.append(str(arg["value"]))
                elif arg.get("isRequired"):
                    result.append("{" + (arg.get("valueHint") or arg.get("name") or "value") + "}")
            return result

        config = {
            "transport": "stdio",
            "command": argv[0],
            "args": arguments(package.get("runtimeArguments", []))
            + argv[1:]
            + arguments(package.get("packageArguments", [])),
        }
        if package.get("environmentVariables"):
            config["env_env"] = {
                item["name"]: item["name"]
                for item in package["environmentVariables"]
                if item.get("isRequired") is not False
            }
        options.append({"label": "stdio · " + kind, "entry": {"name": name, "config": config}})
    return options


async def preview(source, identifier, version):
    provider, base = source["provider"], source["url"]
    kind = PROVIDER_KINDS[provider]
    if provider == "skills_sh":
        entry, version = await skill_entry(identifier)
        options = [{"label": entry["name"], "entry": entry}]
        url = "https://github.com/" + "/".join(identifier.split("/")[:2]) + "/tree/" + version
    elif provider == "mcp_registry":
        url = (
            base
            + "/v0.1/servers/"
            + quote(identifier, safe="")
            + "/versions/"
            + quote(version or "latest", safe="")
        )
        data = await fetch(url)
        if (
            data.get("_meta", {})
            .get("io.modelcontextprotocol.registry/official", {})
            .get("status", "active")
            != "active"
        ):
            raise DomainError("MARKET_ITEM_NOT_FOUND", 404)
        options = mcp_options(data["server"])
        version = data["server"]["version"]
    else:
        if not re.fullmatch(r"(?:@[a-z0-9._-]+/)?[a-z0-9._-]+", identifier) or not re.fullmatch(
            r"[0-9][a-zA-Z0-9.+-]*", version
        ):
            raise DomainError("MARKET_ITEM_NOT_FOUND", 404)
        data = await fetch(base + "/" + quote(identifier, safe="") + "/" + quote(version, safe=""))
        bins = data.get("bin", {})
        if isinstance(bins, str):
            bins = {identifier.split("/")[-1]: bins}
        if not isinstance(bins, dict) or not bins:
            raise DomainError("MARKET_NOT_A_CLI", 422)
        options = []
        for binary in list(bins)[:20]:
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", binary):
                continue
            options.append(
                {
                    "label": binary,
                    "entry": {
                        "name": local_name(binary),
                        "description": data.get("description", ""),
                        "argv": [
                            "npx",
                            "--yes",
                            "--registry=" + base,
                            "--package=" + identifier + "@" + version,
                            "--",
                            binary,
                        ],
                        "argumentMode": "argv",
                        "schema": {
                            "type": "object",
                            "properties": {"args": {"type": "array", "items": {"type": "string"}}},
                            "required": ["args"],
                            "additionalProperties": False,
                        },
                    },
                }
            )
        url = "https://www.npmjs.com/package/" + identifier + "/v/" + version
    if not options:
        raise DomainError("MARKET_NO_SUPPORTED_PACKAGE", 422)
    for option in options:
        option["entry"]["origin"] = {
            "source": source["id"],
            "id": identifier,
            "version": version,
            "url": url,
        }
    return {"kind": kind, "options": options}
