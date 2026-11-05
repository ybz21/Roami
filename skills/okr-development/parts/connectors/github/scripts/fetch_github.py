"""Fetch public repository evidence without writing a project or runtime."""

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        raise ValueError("Repository redirects require source reconciliation")


def collect(repo, timezone_name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", repo):
        raise ValueError("Expected owner/repository")
    if repo.split("/")[1] in {".", ".."}:
        raise ValueError("Invalid repository")
    zone = ZoneInfo(timezone_name)
    request = urllib.request.Request(
        "https://api.github.com/repos/" + repo,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "roami-okr-connector"},
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
        raw = response.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError("Repository response exceeds limit")
    data = json.loads(raw)
    if (
        not isinstance(data, dict)
        or type(data.get("id")) is not int
        or data["id"] <= 0
        or not isinstance(data.get("full_name"), str)
        or data["full_name"].casefold() != repo.casefold()
        or any(
            type(data.get(field)) is not int or data[field] < 0
            for field in ("stargazers_count", "forks_count")
        )
    ):
        raise ValueError("Repository identity or counts are invalid")
    captured = datetime.now(timezone.utc)
    return {
        "schemaVersion": 1,
        "candidateOnly": True,
        "source": {"service": "github", "repo": data["full_name"], "repositoryId": data["id"]},
        "asOf": captured.astimezone(zone).date().isoformat(),
        "capturedAt": captured.isoformat(),
        "values": {"stars": data["stargazers_count"], "forks": data["forks_count"]},
        "evidence": {"sha256": hashlib.sha256(raw).hexdigest(), "payload": data},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--timezone", default="Asia/Shanghai")
    args = parser.parse_args()
    try:
        result = collect(args.repo, args.timezone)
    except (ValueError, urllib.error.URLError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
