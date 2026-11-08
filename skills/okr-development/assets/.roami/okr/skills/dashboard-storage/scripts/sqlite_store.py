#!/usr/bin/env python3
"""Version project source rows; never publish confirmed dashboard data."""

import argparse
import hashlib
import json
import math
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path


def encoded(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise ValueError("Use lowercase schema identifiers")
    return value


def project_path(root, relative):
    if Path(relative).is_absolute():
        raise ValueError("Use a project-relative path")
    target = root / relative
    if not target.resolve().is_relative_to(root) or target.is_symlink():
        raise ValueError("Path must remain inside this project")
    return target


def load(path):
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Request exceeds 4 MiB")
    return json.loads(path.read_text(encoding="utf-8"))


def initialize(connection, project_id):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS okr_source_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT OR IGNORE INTO okr_source_meta VALUES ('projectId', ?)", (project_id,)
    )
    connection.execute(
        "INSERT OR IGNORE INTO okr_source_meta VALUES ('schemaVersion', '1')"
    )
    values = dict(connection.execute("SELECT key, value FROM okr_source_meta"))
    if values != {"projectId": project_id, "schemaVersion": "1"}:
        raise ValueError("Another project or unsupported source schema")
    connection.execute("""CREATE TABLE IF NOT EXISTS okr_source_schemas (
        table_name TEXT NOT NULL, sha256 TEXT NOT NULL, content TEXT NOT NULL,
        sequence INTEGER PRIMARY KEY AUTOINCREMENT, UNIQUE(table_name, sha256))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS okr_source_ingests (
        ingest_key TEXT PRIMARY KEY, sha256 TEXT NOT NULL, receipt TEXT NOT NULL)""")


def validate_schema(value):
    if set(value) != {"table", "label", "key", "columns"}:
        raise ValueError("Schema requires table, label, key and columns")
    table = identifier(value["table"])
    if (
        not table.startswith("src_")
        or not isinstance(value["label"], str)
        or not value["label"].strip()
    ):
        raise ValueError("Source tables use src_ and a nonempty label")
    columns = value["columns"]
    if not isinstance(columns, list) or not 1 <= len(columns) <= 100:
        raise ValueError("Declare 1 to 100 columns")
    names = []
    for column in columns:
        if set(column) != {"id", "label", "type", "nullable", "unit"}:
            raise ValueError("Each column requires id, label, type, nullable and unit")
        names.append(identifier(column["id"]))
        if column["type"] not in {"string", "integer", "number", "boolean"}:
            raise ValueError("Unsupported column type")
        if type(column["nullable"]) is not bool or not isinstance(column["unit"], str):
            raise ValueError("Invalid nullability or unit")
        if not isinstance(column["label"], str) or not column["label"].strip():
            raise ValueError("Column label is required")
    if len(set(names)) != len(names):
        raise ValueError("Duplicate columns")
    keys = value["key"]
    if not isinstance(keys, list) or not keys or len(set(keys)) != len(keys):
        raise ValueError("Declare unique business key columns")
    for key in keys:
        if key not in names or next(c for c in columns if c["id"] == key)["nullable"]:
            raise ValueError("Business keys must be declared nonnullable columns")


def schema(connection, table):
    identifier(table)
    found = connection.execute(
        "SELECT content, sha256 FROM okr_source_schemas WHERE table_name=? ORDER BY sequence DESC LIMIT 1",
        (table,),
    ).fetchone()
    if not found:
        raise ValueError("Apply this source schema first")
    return json.loads(found[0]), found[1]


def apply_schema(connection, value):
    validate_schema(value)
    table, sha = value["table"], digest(value)
    previous = connection.execute(
        "SELECT content FROM okr_source_schemas WHERE table_name=? ORDER BY sequence DESC LIMIT 1",
        (table,),
    ).fetchone()
    if previous:
        old = json.loads(previous[0])
        old_columns = {c["id"]: c for c in old["columns"]}
        new_columns = {c["id"]: c for c in value["columns"]}
        if old["key"] != value["key"] or any(
            new_columns.get(k) != v for k, v in old_columns.items()
        ):
            raise ValueError(
                "Existing columns, units and keys require an explicit migration"
            )
        if any(
            not c["nullable"] for k, c in new_columns.items() if k not in old_columns
        ):
            raise ValueError("New columns must be nullable")
    connection.execute(f'''CREATE TABLE IF NOT EXISTS "{table}" (
        record_key TEXT NOT NULL, row_version INTEGER NOT NULL,
        schema_sha256 TEXT NOT NULL, source_identity TEXT NOT NULL,
        account_id TEXT NOT NULL, as_of TEXT NOT NULL,
        payload TEXT NOT NULL, sha256 TEXT NOT NULL,
        PRIMARY KEY(record_key, row_version))''')
    connection.execute(
        "INSERT OR IGNORE INTO okr_source_schemas (table_name, sha256, content) VALUES (?, ?, ?)",
        (table, sha, encoded(value)),
    )
    return {"table": table, "schemaDigest": sha}


def validate_values(definition, values):
    columns = {c["id"]: c for c in definition["columns"]}
    if not isinstance(values, dict) or set(values) != set(columns):
        raise ValueError("Supply every declared field; use null for unknown")
    for key, value in values.items():
        column = columns[key]
        if value is None:
            if not column["nullable"]:
                raise ValueError("Nonnullable field is missing")
            continue
        kind = column["type"]
        valid = (
            (kind == "string" and isinstance(value, str))
            or (kind == "integer" and type(value) is int)
            or (
                kind == "number"
                and (
                    type(value) is int
                    or (type(value) is float and math.isfinite(value))
                )
            )
            or (kind == "boolean" and type(value) is bool)
        )
        if not valid:
            raise ValueError("Field type differs from declared schema")


def write(connection, root, table, request):
    definition, schema_sha = schema(connection, table)
    if set(request) != {"ingestKey", "schemaDigest", "rows"}:
        raise ValueError("Write requires the exact documented request fields")
    key = request["ingestKey"]
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Use a persistent ingest key")
    sha = digest({"table": table, "request": request})
    existing = connection.execute(
        "SELECT sha256, receipt FROM okr_source_ingests WHERE ingest_key=?", (key,)
    ).fetchone()
    if existing:
        if existing[0] != sha:
            raise ValueError("Ingest key already used with different content")
        return json.loads(existing[1])
    if request["schemaDigest"] != schema_sha:
        raise ValueError("Write requires the current schema digest")
    if not isinstance(request["rows"], list) or not 1 <= len(request["rows"]) <= 1000:
        raise ValueError("Write 1 to 1000 rows per transaction")
    receipts, seen = [], set()
    for row in request["rows"]:
        if set(row) != {
            "values",
            "sourceIdentity",
            "accountId",
            "asOf",
            "capturedAt",
            "evidence",
            "expectedVersion",
        }:
            raise ValueError("Row fields differ from the documented contract")
        validate_values(definition, row["values"])
        if any(
            not isinstance(row[k], str) or not row[k].strip()
            for k in ("sourceIdentity", "accountId")
        ):
            raise ValueError("Source and account must be explicit strings")
        if date.fromisoformat(row["asOf"]).isoformat() != row["asOf"]:
            raise ValueError("asOf must use YYYY-MM-DD")
        captured = datetime.fromisoformat(row["capturedAt"])
        if captured.tzinfo is None or captured.utcoffset() is None:
            raise ValueError("capturedAt must include a timezone")
        evidence = row["evidence"]
        if not isinstance(evidence, dict) or set(evidence) != {"path", "sha256"}:
            raise ValueError("Evidence requires a project-relative path and SHA-256")
        path = project_path(root, evidence["path"])
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Keep large media separate from raw data evidence")
        if hashlib.sha256(path.read_bytes()).hexdigest() != evidence["sha256"]:
            raise ValueError("Evidence digest differs from actual bytes")
        record_key = digest(
            [
                row["sourceIdentity"],
                row["accountId"],
                row["asOf"],
                [row["values"][k] for k in definition["key"]],
            ]
        )
        if record_key in seen:
            raise ValueError("Duplicate business row in this transaction")
        seen.add(record_key)
        previous = connection.execute(
            f'SELECT COALESCE(MAX(row_version), 0) FROM "{table}" WHERE record_key=?',
            (record_key,),
        ).fetchone()[0]
        if (
            type(row["expectedVersion"]) is not int
            or row["expectedVersion"] != previous
        ):
            raise ValueError("Source row changed; reread its current version")
        version = previous + 1
        content = encoded(row)
        connection.execute(
            f'INSERT INTO "{table}" VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                record_key,
                version,
                schema_sha,
                row["sourceIdentity"],
                row["accountId"],
                row["asOf"],
                content,
                hashlib.sha256(content.encode()).hexdigest(),
            ),
        )
        receipts.append(
            {"recordKey": record_key, "rowVersion": version, "schemaDigest": schema_sha}
        )
    receipt = {
        "candidateOnly": True,
        "ingestKey": key,
        "payloadDigest": sha,
        "rows": receipts,
    }
    connection.execute(
        "INSERT INTO okr_source_ingests VALUES (?, ?, ?)", (key, sha, encoded(receipt))
    )
    return receipt


def read(connection, table, source_identity, account_id, as_of, history=False):
    definition, sha = schema(connection, table)
    found = connection.execute(
        f'''SELECT record_key, row_version, schema_sha256, payload, sha256
        FROM "{table}" WHERE source_identity=? AND account_id=? AND as_of=?
        ORDER BY record_key, row_version''',
        (source_identity, account_id, as_of),
    ).fetchall()
    rows = [
        {
            "recordKey": r[0],
            "rowVersion": r[1],
            "schemaDigest": r[2],
            "row": json.loads(r[3]),
            "sha256": r[4],
        }
        for r in found
    ]
    if not history:
        rows = list({r["recordKey"]: r for r in rows}.values())
    return {
        "candidateOnly": True,
        "schema": definition,
        "schemaDigest": sha,
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("init")
    apply = sub.add_parser("schema-apply")
    apply.add_argument("--file", type=Path, required=True)
    add = sub.add_parser("write")
    add.add_argument("--table", required=True)
    add.add_argument("--file", type=Path, required=True)
    for name in ("read", "export"):
        query = sub.add_parser(name)
        query.add_argument("--table", required=True)
        query.add_argument("--source-identity", required=True)
        query.add_argument("--account-id", required=True)
        query.add_argument("--as-of", required=True)
        query.add_argument("--history", action="store_true")
    backup = sub.add_parser("backup")
    backup.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        root = args.project_root.resolve(strict=True)
        if not args.project_id.strip() or "{{" in args.project_id:
            raise ValueError("Use the real project ID")
        target = project_path(root, ".roami/okr/data/source.sqlite3")
        if args.operation == "init":
            target.parent.mkdir(parents=True, exist_ok=True)
        if args.operation != "init" and not target.exists():
            raise ValueError("Initialize this project's source database first")
        readonly = args.operation in {"read", "export", "backup"}
        mode = "ro" if readonly else ("rwc" if args.operation == "init" else "rw")
        with sqlite3.connect(
            target.as_uri() + "?mode=" + mode,
            uri=True,
            isolation_level=None,
            timeout=10,
        ) as connection:
            connection.execute("BEGIN" if readonly else "BEGIN IMMEDIATE")
            try:
                if readonly:
                    metadata = dict(
                        connection.execute("SELECT key, value FROM okr_source_meta")
                    )
                    if metadata != {"projectId": args.project_id, "schemaVersion": "1"}:
                        raise ValueError("Another project or unsupported source schema")
                else:
                    initialize(connection, args.project_id)
                if args.operation == "init":
                    result = {
                        "candidateOnly": True,
                        "projectId": args.project_id,
                        "initialized": True,
                    }
                elif args.operation == "schema-apply":
                    result = apply_schema(connection, load(args.file))
                elif args.operation == "write":
                    result = write(connection, root, args.table, load(args.file))
                elif args.operation in {"read", "export"}:
                    result = read(
                        connection,
                        args.table,
                        args.source_identity,
                        args.account_id,
                        args.as_of,
                        args.history,
                    )
                else:
                    result = {"candidateOnly": True, "backup": args.output}
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            if args.operation == "backup":
                output = project_path(root, args.output)
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("xb"):
                    pass
                with sqlite3.connect(output) as destination:
                    connection.backup(destination)
                    if (
                        destination.execute("PRAGMA integrity_check").fetchone()[0]
                        != "ok"
                    ):
                        raise ValueError("Backup integrity check failed")
            print(encoded(result))
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
