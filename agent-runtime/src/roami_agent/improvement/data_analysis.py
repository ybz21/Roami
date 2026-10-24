"""DSBench workbook questions with frozen inputs and host-only answer keys."""

import base64
import json
import re
import zipfile
from pathlib import PurePosixPath

from roami_agent.improvement.contracts import digest, freeze_suite, require


def import_data_analysis(metadata, archive, *, group_id, question_id, revision, upstream_revision):
    require(bool(re.fullmatch(r"[0-9]{8}", group_id)))
    require(bool(re.fullmatch(r"question[0-9]+", question_id)))
    require(all(re.fullmatch(r"[a-f0-9]{40}", value) for value in (revision, upstream_revision)))
    require(metadata.stat().st_size <= 2_000_000 and archive.stat().st_size <= 20_000_000)
    records = [json.loads(line) for line in metadata.read_text().splitlines() if line.strip()]
    matches = [record for record in records if record["id"] == group_id]
    require(
        len(matches) == 1 and question_id in matches[0]["questions"], "RSI_SOURCE_TASK_REQUIRED"
    )
    record = matches[0]
    expected = record["answers"][record["questions"].index(question_id)]
    require(type(expected) in {str, int, float}, "RSI_SOURCE_ORACLE_REQUIRED")
    prefix = "data/" + group_id + "/"
    files, assets = {}, {}
    with zipfile.ZipFile(archive) as bundle:
        require(len(bundle.infolist()) <= 10000)
        members = [m for m in bundle.infolist() if m.filename.startswith(prefix) and not m.is_dir()]
        require(
            len(members) <= 1000 and sum(m.file_size for m in members) <= 24_000_000,
            "RSI_INPUT_TOO_LARGE",
        )
        for member in members:
            require(".." not in PurePosixPath(member.filename).parts)
            name = PurePosixPath(member.filename).name
            if not name.endswith((".txt", ".xlsx")):
                continue
            require(member.file_size <= 10_000_000, "RSI_INPUT_TOO_LARGE")
            require(name not in files and name not in assets, "RSI_DUPLICATE_SOURCE_ID")
            data = bundle.read(member)
            if name.endswith(".txt"):
                files[name] = data.decode("utf-8-sig")
            else:
                assets[name] = base64.b64encode(data).decode()
    require("introduction.txt" in files and question_id + ".txt" in files and bool(assets))
    case = {
        "id": "dsbench:" + group_id + ":" + question_id,
        "category": "DATA",
        "layer": "public_agent",
        "split": "public_test",
        "cluster": "dsbench:competition:" + group_id,
        "prompt": "Analyze the supplied workbook and introduction. Answer ONLY "
        + question_id
        + ":\n"
        + files[question_id + ".txt"]
        + "\nOther question files provide background definitions, not extra requested answers. Save the final answer as one JSON value in result.json (a quoted string or number as requested), without an enclosing object. Preserve source inputs. Installed openpyxl/NumPy/pandas may be used offline. For execution delegate to native Worker in /workspace; shell calls use cwd=/workspace. This final-value adaptation is not the official LLM-judged benchmark score.",
        "files": files,
        "asset_files": assets,
        "counts_as_delivery": True,
        "limits": {"seconds": 900, "tokens": 384000, "requests": 64},
        "judge": {"kind": "json", "path": "result.json", "expected": expected},
        "origin": {
            "benchmark": "dsbench",
            "task_id": group_id + ":" + question_id,
            "revision": revision,
            "upstream_revision": upstream_revision,
            "source_split": "data_analysis",
            "input_sha256": digest({"files": files, "assets": assets}),
            "adapter_revision": "dsbench-final-value-v1",
            "adapted": True,
            "adaptation": "Frozen original workbook, introduction and questions; exact selected JSON answer instead of the upstream LLM judge. Not official-score comparable.",
        },
    }
    return freeze_suite(
        "dsbench-" + group_id + "-" + question_id + "-v1",
        [case],
        official_leaderboard_comparable=False,
    )
