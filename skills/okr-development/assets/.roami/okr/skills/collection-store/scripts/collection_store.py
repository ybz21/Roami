#!/usr/bin/env python3
"""Keep project publication registrations separate from confirmed OKR data."""

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def database_path(project):
    root = project.resolve(strict=True)
    directory = root / ".roami/okr/data"
    if not directory.resolve().is_relative_to(root):
        raise ValueError("Collection directory must remain inside this project")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "collection.sqlite3"
    if not target.resolve().is_relative_to(root) or target.is_symlink():
        raise ValueError("Collection database must remain inside this project")
    return target


def validate_publication(value):
    required = {
        "businessKey",
        "platform",
        "accountId",
        "objectId",
        "url",
        "publishedAt",
        "mainReviewReceipt",
        "evidenceSha256",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Publication requires the documented exact fields")
    if any(not isinstance(item, str) or not item.strip() for item in value.values()):
        raise ValueError("Publication fields must be nonempty strings")
    evidence = value["evidenceSha256"]
    if len(evidence) != 64 or any(char not in "0123456789abcdef" for char in evidence):
        raise ValueError("evidenceSha256 must be a lowercase SHA-256")
    if not value["url"].startswith("https://"):
        raise ValueError("Publication URL must use HTTPS")
    published = datetime.fromisoformat(value["publishedAt"])
    if published.tzinfo is None or published.utcoffset() is None:
        raise ValueError("Publication timestamp must include its timezone")


def initialize(connection, project_id):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute("INSERT OR IGNORE INTO metadata VALUES ('projectId', ?)", (project_id,))
    stored = connection.execute("SELECT value FROM metadata WHERE key='projectId'").fetchone()[0]
    if stored != project_id:
        raise ValueError("Database belongs to another project")
    connection.execute("""CREATE TABLE IF NOT EXISTS publications (
        business_key TEXT PRIMARY KEY,
        platform TEXT NOT NULL, account_id TEXT NOT NULL, object_id TEXT NOT NULL,
        content TEXT NOT NULL, sha256 TEXT NOT NULL,
        UNIQUE(platform, account_id, object_id))""")
    connection.execute("INSERT OR IGNORE INTO metadata VALUES ('schemaVersion', '1')")
    version = connection.execute("SELECT value FROM metadata WHERE key='schemaVersion'").fetchone()[
        0
    ]
    if version != "1":
        raise ValueError("Unsupported collection schema")
    connection.execute("""CREATE TABLE IF NOT EXISTS publication_versions (
        business_key TEXT NOT NULL, version INTEGER NOT NULL,
        content TEXT NOT NULL, sha256 TEXT NOT NULL,
        PRIMARY KEY(business_key, version))""")


def register(connection, value, expected_sha256=None):
    validate_publication(value)
    key = value["businessKey"]
    previous = connection.execute(
        "SELECT content, sha256 FROM publications WHERE business_key=?", (key,)
    ).fetchone()
    sha = digest(value)
    if previous and previous[1] == sha:
        return {"changed": False, "sha256": sha}
    if previous:
        old = json.loads(previous[0])
        if any(old[field] != value[field] for field in ("platform", "accountId", "objectId")):
            raise ValueError("Publication identity is immutable")
        if expected_sha256 != previous[1]:
            raise ValueError("Publication changed; reread and provide expected SHA-256")
        connection.execute(
            "UPDATE publications SET content=?, sha256=? WHERE business_key=?",
            (encoded(value), sha, key),
        )
    else:
        if expected_sha256 is not None:
            raise ValueError("Expected publication does not exist")
        connection.execute(
            "INSERT INTO publications VALUES (?, ?, ?, ?, ?, ?)",
            (
                key,
                value["platform"],
                value["accountId"],
                value["objectId"],
                encoded(value),
                sha,
            ),
        )
    version = connection.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM publication_versions WHERE business_key=?",
        (key,),
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO publication_versions VALUES (?, ?, ?, ?)",
        (key, version, encoded(value), sha),
    )
    return {"changed": True, "sha256": sha}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("init")
    add = sub.add_parser("register-publication")
    add.add_argument("--file", type=Path, required=True)
    add.add_argument("--expected-sha256")
    listing = sub.add_parser("list-publications")
    listing.add_argument("--platform", required=True)
    listing.add_argument("--account-id", required=True)
    history = sub.add_parser("publication-history")
    history.add_argument("--business-key", required=True)
    args = parser.parse_args()
    if not args.project_id.strip() or "{{" in args.project_id:
        parser.error("Use the real project ID")
    try:
        target = database_path(args.project)
        if args.operation != "init" and not target.exists():
            parser.error("Initialize the project collection database first")
        with sqlite3.connect(target, isolation_level=None, timeout=10) as connection:
            connection.execute("BEGIN IMMEDIATE")
            initialize(connection, args.project_id)
            if args.operation == "register-publication":
                value = json.loads(args.file.read_text(encoding="utf-8"))
                result = register(connection, value, args.expected_sha256)
            elif args.operation == "list-publications":
                rows = connection.execute(
                    "SELECT content, sha256 FROM publications WHERE platform=? AND account_id=? ORDER BY business_key",
                    (args.platform, args.account_id),
                ).fetchall()
                result = {
                    "publications": [
                        {"publication": json.loads(row[0]), "sha256": row[1]} for row in rows
                    ]
                }
                result["coverageSha256"] = digest(result["publications"])
            elif args.operation == "publication-history":
                rows = connection.execute(
                    "SELECT version, content, sha256 FROM publication_versions WHERE business_key=? ORDER BY version",
                    (args.business_key,),
                ).fetchall()
                result = {
                    "versions": [
                        {"version": row[0], "publication": json.loads(row[1]), "sha256": row[2]}
                        for row in rows
                    ]
                }
            else:
                result = {"initialized": True, "schemaVersion": 1}
            connection.commit()
    except (ValueError, sqlite3.Error, OSError) as error:
        parser.exit(1, f"{error}\n")
    print(encoded({"projectId": args.project_id, **result}))


if __name__ == "__main__":
    main()
