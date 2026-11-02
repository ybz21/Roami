"""Readable case metadata with separate execution contracts and frozen run identities."""

import json
import re
from functools import lru_cache
from pathlib import Path

from roami_agent.improvement.domain.contracts import require
from roami_agent.protocol.errors import DomainError


def case_root():
    packaged = Path(__file__).parents[1] / "cases"
    if packaged.is_dir():
        return packaged
    project = Path(__file__).parents[4]
    return project / "cases" if (project / "cases").is_dir() else project.parent / "cases"


def read_definition(folder):
    require(re.fullmatch(r"case-[1-9][0-9]*-[a-z0-9-]+", folder.name), "RSI_CASE_DIRECTORY_INVALID")
    require(not folder.is_symlink(), "RSI_CASE_DIRECTORY_INVALID")
    document = folder / "CASE.md"
    contract = folder / "case.json"
    require(
        document.is_file()
        and contract.is_file()
        and not document.is_symlink()
        and not contract.is_symlink(),
        "RSI_CASE_METADATA_REQUIRED",
    )
    require(document.stat().st_size <= 64000 and contract.stat().st_size <= 1000000)
    text = document.read_text(encoding="utf-8")
    require(text.startswith("---\n") and "\n---\n" in text[4:], "RSI_CASE_METADATA_REQUIRED")
    header = text[4:].split("\n---\n", 1)[0]
    metadata = {}
    for line in header.splitlines():
        key, separator, raw = line.partition(":")
        require(
            separator and key in {"name", "description"} and key not in metadata,
            "RSI_CASE_METADATA_INVALID",
        )
        raw = raw.strip()
        try:
            value = json.loads(raw) if raw.startswith('"') else raw
        except ValueError as error:
            raise DomainError("RSI_CASE_METADATA_INVALID") from error
        require(
            isinstance(value, str) and 0 < len(value.strip()) <= 10000, "RSI_CASE_METADATA_REQUIRED"
        )
        metadata[key] = value
    require(set(metadata) == {"name", "description"}, "RSI_CASE_METADATA_REQUIRED")
    try:
        value = json.loads(contract.read_text(encoding="utf-8"))
    except ValueError as error:
        raise DomainError("RSI_CASE_CONTRACT_INVALID") from error
    require(
        isinstance(value, dict) and not ({"name", "description", "title"} & set(value)),
        "RSI_CASE_METADATA_DUPLICATED",
    )
    require(
        isinstance(value.get("id"), str) and folder.name.endswith("-" + value["id"].lower()),
        "RSI_CASE_ID_MISMATCH",
    )
    resources = value.get("resources", {})
    require(
        isinstance(resources, dict)
        and set(resources)
        <= {"inputs", "tools", "generator", "provenance", "acceptance", "materials"},
        "RSI_CASE_RESOURCES_INVALID",
    )
    for resource in resources.values():
        names = resource if isinstance(resource, list) else [resource]
        require(0 < len(names) <= 64, "RSI_CASE_RESOURCES_INVALID")
        for name in names:
            resource_file(folder, name)
    return {**value, **metadata}


@lru_cache(maxsize=1)
def case_definitions():
    folders = list(case_root().glob("case-*"))
    require(
        all(re.fullmatch(r"case-[1-9][0-9]*-[a-z0-9-]+", p.name) for p in folders),
        "RSI_CASE_DIRECTORY_INVALID",
    )
    folders.sort(key=lambda path: int(path.name.split("-", 2)[1]))
    values = tuple(read_definition(folder) for folder in folders)
    require(
        values and len({value["id"] for value in values}) == len(values),
        "RSI_CASE_CATALOG_INCOMPLETE",
    )
    require(
        len({folder.name.split("-", 2)[1] for folder in folders}) == len(values),
        "RSI_CASE_DIRECTORY_INVALID",
    )
    return values


def authored_cases():
    values = tuple(
        value
        for value in case_definitions()
        if value["kind"] != "public_source_reference"
        and value.get("selected_in_mixed_suite_v1", True)
    )
    require(len(values) == 40, "RSI_CASE_CATALOG_INCOMPLETE")
    return values


def case_identity(case):
    protected = case.get("split") in {"holdout", "validation"}
    spec = next(
        (
            value
            for value in case_definitions()
            if value["id"] == case["id"] or value.get("source_case_id") == case["id"]
        ),
        {},
    )
    origin = case.get("origin", {})
    return {
        "id": case["id"],
        "name": case["id"]
        if protected
        else case.get("name")
        or spec.get("name")
        or (str(origin.get("benchmark", case.get("category", "Case"))) + " / " + case["id"]),
        "description": ""
        if protected
        else (case.get("description") or spec.get("description") or case.get("prompt", ""))[:10000],
        "category": case.get("category"),
        "layer": case.get("layer"),
        "protected": protected,
    }


def resource_file(folder, name):
    from roami_agent.improvement.integrations.artifact_paths import relative_file

    path = relative_file(folder, name)
    require(
        path.is_file() and not path.is_symlink() and path.stat().st_size <= 4_000_000,
        "RSI_CASE_RESOURCE_UNAVAILABLE",
    )
    return path


def case_resource(case_id, name):
    folders = [
        folder
        for folder in case_root().glob("case-*")
        if folder.name.endswith("-" + case_id.lower())
    ]
    require(len(folders) == 1 and not folders[0].is_symlink(), "RSI_CASE_RESOURCE_UNAVAILABLE")
    return resource_file(folders[0], name)


def resource_hashes(spec):
    import hashlib

    resources = spec.get("resources", {})
    names = [
        name
        for value in resources.values()
        for name in (value if isinstance(value, list) else [value])
    ]
    return {
        name: hashlib.sha256(case_resource(spec["id"], name).read_bytes()).hexdigest()
        for name in names
    }
