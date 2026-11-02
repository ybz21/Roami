"""Download public GitHub skills without depending on anonymous REST API quota."""

import asyncio
import base64
import io
import os
import re
import tarfile
import zlib
from pathlib import PurePosixPath
from tempfile import TemporaryDirectory

from roami_agent.protocol.errors import DomainError
from roami_agent.server.skill_package import MAX_PACKAGE_BYTES
from roami_agent.tools.process import execute


def unpack_skill(archive, skill):
    try:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        expanded = decoder.decompress(archive, 32_000_001)
        if len(expanded) > 32_000_000 or decoder.unconsumed_tail:
            raise DomainError("MARKET_PACKAGE_TOO_LARGE", 413)
        if not decoder.eof:
            raise DomainError("INVALID_SKILL_PACKAGE")
        with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as bundle:
            members = {}
            candidates = []
            for index, member in enumerate(bundle):
                if index >= 10000:
                    raise DomainError("MARKET_PACKAGE_TOO_LARGE", 413)
                path = member.name.partition("/")[2]
                if path in members:
                    raise DomainError("INVALID_SKILL_PACKAGE")
                members[path] = member
                if member.isfile() and path.endswith("SKILL.md") and member.size <= 64000:
                    content = bundle.extractfile(member).read().decode("utf-8", errors="replace")
                    match = re.search(r"(?m)^name:\s*[\"']?([^\s\"']+)", content)
                    if PurePosixPath(path).parent.name == skill or match and match[1] == skill:
                        candidates.append(path)
            if len(candidates) != 1:
                raise DomainError("MARKET_SKILL_PATH_REQUIRED", 409)
            prefix = candidates[0].removesuffix("SKILL.md")
            selected = {
                name: member
                for name, member in members.items()
                if name.startswith(prefix) and not member.isdir()
            }
            for license_name in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
                if prefix and prefix + license_name not in selected and license_name in members:
                    selected[license_name] = members[license_name]
            if (
                len(selected) > 100
                or sum(member.size for member in selected.values()) > MAX_PACKAGE_BYTES
            ):
                raise DomainError("MARKET_PACKAGE_TOO_LARGE", 413)
            if any(not member.isfile() for member in selected.values()):
                raise DomainError("INVALID_SKILL_PACKAGE")
            contents = {
                name.removeprefix(prefix) if name.startswith(prefix) else name: bundle.extractfile(
                    member
                ).read()
                for name, member in selected.items()
            }
            text = contents["SKILL.md"].decode("utf-8")
            return text, {name: base64.b64encode(raw).decode() for name, raw in contents.items()}
    except (tarfile.TarError, zlib.error, UnicodeDecodeError, KeyError, OSError):
        raise DomainError("INVALID_SKILL_PACKAGE") from None


async def download_archive(owner, repo, skill, fetch):
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "PATH",
            "HTTPS_PROXY",
            "HTTP_PROXY",
            "ALL_PROXY",
            "NO_PROXY",
            "https_proxy",
            "http_proxy",
            "all_proxy",
            "no_proxy",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
        }
    }
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    try:
        with TemporaryDirectory(prefix="roami-skill-source-") as directory:
            result = await execute(
                [
                    "git",
                    "-c",
                    "credential.helper=",
                    "ls-remote",
                    f"https://github.com/{owner}/{repo}.git",
                    "HEAD",
                ],
                cwd=directory,
                env=env,
                timeout=20,
                max_bytes=4096,
            )
        commit = result["stdout"].split()[0] if result["exitCode"] == 0 and result["stdout"] else ""
        if not re.fullmatch(r"[a-f0-9]{40}", commit):
            raise DomainError("MARKET_UNAVAILABLE", 502)
        archive = await fetch(
            f"https://codeload.github.com/{owner}/{repo}/tar.gz/{commit}",
            raw=True,
            maximum=8_000_000,
        )
        text, files = await asyncio.to_thread(unpack_skill, archive, skill)
        return text, files, commit
    except OSError:
        raise DomainError("MARKET_UNAVAILABLE", 502) from None
