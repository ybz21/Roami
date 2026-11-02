import hashlib
import json
import subprocess
import sys
from pathlib import Path

from pptx import Presentation

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/report.py"
FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "cases/case-99-mech-mp01/input/calendar-series.csv"
)


def command(root, *extra):
    return [
        sys.executable,
        str(SCRIPT),
        "--workspace",
        str(root),
        "--path",
        "clean.csv",
        "--date",
        "When",
        "--price",
        "Value",
        "--volume",
        "Activity",
        "--short",
        "2",
        "--long",
        "3",
        "--destination",
        "report",
        *extra,
    ]


def test_real_saved_deck_render_and_new_destination_publication(tmp_path):
    original = FIXTURE.read_bytes()
    (tmp_path / "clean.csv").write_bytes(original)
    (tmp_path / "raw.csv").write_bytes(original)
    run = subprocess.run(
        command(tmp_path, "--source-schema", "raw.csv"),
        check=False,
        capture_output=True,
        text=True,
        timeout=260,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    receipt = json.loads(run.stdout)
    assert receipt["ok"] and receipt["writePublished"] is True
    assert receipt["visualInspectionPerformed"] is False
    destination = tmp_path / "report"
    deck = destination / "report.pptx"
    assert len(Presentation(deck).slides) == 9
    manifest = json.loads((destination / "review-manifest.json").read_text())
    assert manifest["deckSha256"] == hashlib.sha256(deck.read_bytes()).hexdigest()
    assert manifest["pageCount"] == 9
    for page in manifest["pages"]:
        body = (destination / page["path"]).read_bytes()
        assert body.startswith(b"\x89PNG\r\n\x1a\n")
        assert hashlib.sha256(body).hexdigest() == page["sha256"]
    assert (tmp_path / "clean.csv").read_bytes() == original
    assert (tmp_path / "raw.csv").read_bytes() == original
    before = {
        str(p.relative_to(destination)): p.read_bytes()
        for p in destination.rglob("*")
        if p.is_file()
    }
    again = subprocess.run(
        command(tmp_path), check=False, capture_output=True, text=True, timeout=30
    )
    assert again.returncode == 2
    assert json.loads(again.stdout)["writePublished"] is False
    assert before == {
        str(p.relative_to(destination)): p.read_bytes()
        for p in destination.rglob("*")
        if p.is_file()
    }


def test_cleaned_export_schema_mismatch_refused_before_publication(tmp_path):
    (tmp_path / "clean.csv").write_bytes(FIXTURE.read_bytes())
    (tmp_path / "raw.csv").write_text("record,When,Value,Activity\n1,2024-01-01,10,1\n")
    run = subprocess.run(
        command(tmp_path, "--source-schema", "raw.csv"),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 2
    receipt = json.loads(run.stdout)
    assert "CLEANED_CSV_SCHEMA_CHANGED" in receipt["error"]
    assert receipt["writePublished"] is False
    assert not (tmp_path / "report").exists()
