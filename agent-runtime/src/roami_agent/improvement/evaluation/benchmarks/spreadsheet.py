"""Offline workbook-value adapter; formulas need saved values, never an invented score."""

import base64
import io
import json
import math
import re
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

from roami_agent.improvement.domain.contracts import DIMENSIONS, digest, require
from roami_agent.improvement.domain.scoring import quality
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.protocol.errors import DomainError

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
FRACTIONAL_CELL_TOLERANCE = 2e-15


def same_cell_value(actual, expected):
    from roami_agent.improvement.domain.scoring import same_json

    if type(actual) in {int, float} and type(expected) in {int, float}:
        if not math.isfinite(actual) or not math.isfinite(expected):
            return False
        if float(actual).is_integer() or float(expected).is_integer():
            return actual == expected
        # XLSX time values can gain binary tail bits when an editor saves them again.
        return math.isclose(actual, expected, rel_tol=FRACTIONAL_CELL_TOLERANCE, abs_tol=0)
    return same_json(actual, expected)


def workbook(data):
    require(len(data) <= 16_000_000, "RSI_INPUT_TOO_LARGE")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        require(len(members) <= 2048 and sum(m.file_size for m in members) <= 64_000_000)
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        links = {
            r.attrib["Id"]: r.attrib["Target"]
            for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = [
                "".join(t.text or "" for t in row.findall(".//m:t", NS))
                for row in ET.fromstring(archive.read("xl/sharedStrings.xml"))
            ]
        sheets = {}
        for sheet in book.findall("m:sheets/m:sheet", NS):
            target = links[sheet.attrib[REL]]
            path = target.lstrip("/") if target.startswith("/") else "xl/" + target
            require(".." not in PurePosixPath(path).parts)
            tree = ET.fromstring(archive.read(path))
            cells = {}
            for cell in tree.findall(".//m:sheetData/m:row/m:c", NS):
                kind = cell.attrib.get("t", "n")
                raw = cell.findtext("m:v", default="", namespaces=NS)
                if kind == "inlineStr":
                    value = "".join(t.text or "" for t in cell.findall(".//m:t", NS))
                elif kind == "s":
                    value = strings[int(raw)]
                elif kind == "b":
                    require(raw in {"0", "1"})
                    value = raw == "1"
                elif kind == "n" and raw:
                    value = float(raw)
                    require(math.isfinite(value))
                else:
                    value = raw or None
                if value is not None:
                    cells[cell.attrib["r"]] = value
            sheets[sheet.attrib["name"]] = {
                "cells": cells,
                "merges": [x.attrib["ref"] for x in tree.findall("m:mergeCells/m:mergeCell", NS)],
            }
    require(bool(sheets))
    return sheets


def cell_range(value):
    match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*):([A-Z]{1,3})([1-9][0-9]*)", value)
    require(match is not None, "RSI_WORKBOOK_RANGE")

    def column(text):
        result = 0
        for ch in text:
            result = result * 26 + ord(ch) - 64
        return result

    a, first, b, last = match.groups()
    left, right = column(a), column(b)
    require(1 <= left <= right <= 16384 and 1 <= int(first) <= int(last) <= 1048576)
    require((right - left + 1) * (int(last) - int(first) + 1) <= 10000)

    def label(number):
        text = ""
        while number:
            number, digit = divmod(number - 1, 26)
            text = chr(65 + digit) + text
        return text

    return [
        label(col) + str(row)
        for col in range(left, right + 1)
        for row in range(int(first), int(last) + 1)
    ]


def import_spreadsheet(metadata, source, golden, *, revision, upstream_revision):
    require(all(re.fullmatch(r"[a-f0-9]{40}", r) for r in (revision, upstream_revision)))
    record = json.loads(metadata.read_text())
    require("unmerge" in record["instruction"].lower(), "RSI_WORKBOOK_ADAPTER_SCOPE")
    initial, reference = workbook(source.read_bytes()), workbook(golden.read_bytes())
    require(set(initial) == set(reference))
    sheet = next(iter(initial))
    positions = cell_range(record["answer_position"])
    expected = {p: reference[sheet]["cells"].get(p) for p in positions}
    require(any(v is not None for v in expected.values()), "RSI_WORKBOOK_ORACLE_REQUIRED")
    inputs = base64.b64encode(source.read_bytes()).decode()
    task_id = "verified400:" + str(record["id"])
    case = {
        "id": "spreadsheetbench:" + str(record["id"]),
        "category": "DATA",
        "layer": "public_component",
        "split": "public_test",
        "cluster": "spreadsheetbench:" + str(record["id"]),
        "prompt": record["instruction"]
        + "\nEdit input.xlsx and save result.xlsx. Keep other cell values and sheets. All merges must be removed. The grader checks saved values in "
        + sheet
        + "!"
        + record["answer_position"]
        + "; write computed values or formulas with correct cached values. Fractional numeric cells allow relative rounding error up to 2e-15 with no absolute tolerance; integral numbers, text and booleans remain exact. This is a single-workbook adaptation, not the official benchmark score.",
        "counts_as_delivery": True,
        "files": {},
        "asset_files": {"input.xlsx": inputs},
        "limits": {"seconds": 300, "tokens": 128000, "requests": 24},
        "judge": {"kind": "workbook", "path": "result.xlsx", "sheet": sheet, "expected": expected},
        "origin": {
            "benchmark": "spreadsheetbench",
            "task_id": task_id,
            "revision": revision,
            "upstream_revision": upstream_revision,
            "source_split": "verified_400",
            "input_sha256": digest({"record": record, "input": inputs}),
            "adapter_revision": "spreadsheet-values-v2-fractional-roundtrip",
            "adapted": True,
            "adaptation": "One workbook; saved target values, preserved input cells and unmerged cells; no formula recalculation or official OJ comparability.",
        },
    }
    return freeze_suite(
        "spreadsheetbench-verified400-sample-v1", [case], official_leaderboard_comparable=False
    )


def grade_workbook(case, workspace):
    checks = {}
    try:
        from roami_agent.improvement.integrations.artifact_paths import relative_file

        spec = case["judge"]
        path = relative_file(workspace, spec["path"])
        require(path.stat().st_size <= 16_000_000)
        actual = workbook(path.read_bytes())
        initial = workbook(base64.b64decode(case["asset_files"]["input.xlsx"]))
        checks["sheets_preserved"] = actual.keys() == initial.keys()
        checks["target_values"] = all(
            same_cell_value(actual[spec["sheet"]]["cells"].get(p), v)
            for p, v in spec["expected"].items()
        )
        checks["input_values_preserved"] = all(
            same_cell_value(actual.get(name, {}).get("cells", {}).get(p), v)
            for name, sheet in initial.items()
            for p, v in sheet["cells"].items()
            if name != spec["sheet"] or p not in spec["expected"]
        )
        checks["unmerged"] = all(not s["merges"] for s in actual.values())
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        DomainError,
        ET.ParseError,
        zipfile.BadZipFile,
    ):
        checks["verification_completed"] = False

    passed = bool(checks) and all(checks.values())
    return {
        **quality(dict.fromkeys(DIMENSIONS, 3 if passed else 0), hard_passed=passed),
        "checks": checks,
        "grade_scope": "adapted_workbook_values",
        "numeric_comparison": {
            "fractional_relative_tolerance": FRACTIONAL_CELL_TOLERANCE,
            "absolute_tolerance": 0,
            "integral_values_exact": True,
        },
        "official_leaderboard_comparable": False,
    }
