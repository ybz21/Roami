"""Fetch public repository evidence without writing a project or runtime."""

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from zoneinfo import ZoneInfo


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        raise ValueError("Repository redirects require source reconciliation")


def collect(repo, timezone_name, repository_id=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", repo):
        raise ValueError("Expected owner/repository")
    if repo.split("/")[1] in {".", ".."}:
        raise ValueError("Invalid repository")
    if repository_id is not None and (
        type(repository_id) is not int or repository_id <= 0
    ):
        raise ValueError("Expected a positive repository ID")
    zone = ZoneInfo(timezone_name)
    request = urllib.request.Request(
        "https://api.github.com/repos/" + repo,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "roami-okr-connector",
        },
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
        status = response.status
        if status != 200:
            raise ValueError("Expected an HTTP 200 repository response")
        headers = {
            name: response.headers[name]
            for name in (
                "Date",
                "ETag",
                "Last-Modified",
                "Content-Type",
                "X-GitHub-Request-Id",
            )
            if name in response.headers
        }
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
    if repository_id is not None and data["id"] != repository_id:
        raise ValueError("Repository ID changed; source reconciliation required")
    captured = datetime.now(UTC)
    return {
        "schemaVersion": 1,
        "candidateOnly": True,
        "source": {
            "service": "github",
            "repo": data["full_name"],
            "repositoryId": data["id"],
        },
        "asOf": captured.astimezone(zone).date().isoformat(),
        "capturedAt": captured.isoformat(),
        "values": {"stars": data["stargazers_count"], "forks": data["forks_count"]},
        "evidence": {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "payload": data,
            "http": {"status": status, "headers": headers, "body": raw.decode("utf-8")},
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--repository-id", type=int)
    args = parser.parse_args()
    try:
        result = collect(args.repo, args.timezone, args.repository_id)
    except (ValueError, urllib.error.URLError, TimeoutError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
