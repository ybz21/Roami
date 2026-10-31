"""Native evidence and live render sources cannot drift into a passing artifact review."""

import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest
from test_improvement_artifact_review import rating, reviewer

from roami_agent.improvement.evaluation import artifact_evidence
from roami_agent.improvement.evaluation.artifact_evidence import collect_artifact_evidence
from roami_agent.improvement.evaluation.execution.executors import ProtocolFixtureModel
from roami_agent.protocol.errors import DomainError

FIXTURE = Path(__file__).resolve().parent / "fixtures/artifact-sources.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup(root):
    data = json.loads(FIXTURE.read_text())
    workspace = root / "stock-remote"
    workspace.mkdir()
    for name, text in data["files"].items():
        (workspace / name).write_text(text)
    snapshot = root / "stock-snapshot.json"
    snapshot.write_text(json.dumps(data["snapshot"]))
    case = {
        "id": "the-agent-company:ds-stock-analysis-slides",
        "grading_profile": "presentation",
        "prompt": "Review these synthetic artifacts.",
        "judge": {
            "kind": "company_stock",
            "golden": base64.b64encode((workspace / "stock_cleaned.csv").read_bytes()).decode(),
        },
    }
    grade = {
        "hard_passed": True,
        "passed": False,
        "pending": True,
        "quality": 0,
        "checks": {"fixture_native_check": True},
        "native_partial": {"unscored_points": 7},
        "evidence": [
            {"remote_path": name, "sha256": sha(workspace / name)} for name in data["files"]
        ]
        + [{"source": "host_native_snapshot", "sha256": sha(snapshot)}],
    }
    return case, grade


class Renderer:
    image_id = "sha256:" + "f" * 64

    def __init__(self, mutate=None):
        self.calls = 0
        self.mutate = mutate

    async def sandbox(self, *args, **kwargs):
        self.calls += 1
        if self.mutate:
            self.mutate(self.calls)
        if self.calls == 2:
            return b'{"fixture_summary":true}'
        return json.dumps(
            {
                "images": [
                    {
                        "label": "rendered page",
                        "mime": "image/jpeg",
                        "data": base64.b64encode(b"fixture rendered image").decode(),
                    }
                ],
                "texts": [
                    {
                        "label": "stock_analysis_script.md",
                        "text": "Synthetic narrative.",
                        "truncated": False,
                    }
                ],
            }
        ).encode()


def source(root, name):
    return root / "stock-snapshot.json" if name == "snapshot" else root / "stock-remote" / name


async def test_unchanged_native_sources_keep_the_existing_review_input(tmp_path):
    case, grade = setup(tmp_path)
    original = copy.deepcopy(grade)
    renderer = Renderer()
    pack = await collect_artifact_evidence(case, grade, tmp_path, renderer)
    assert renderer.calls == 2 and grade == original
    assert {x["file"] for x in pack["artifacts"]} == {
        "stock_analysis.pptx",
        "stock_analysis_script.md",
    }
    assert (tmp_path / "artifact-evidence.json").is_file()


@pytest.mark.parametrize(
    "name", ["stock_analysis.pptx", "stock_analysis_script.md", "stock_cleaned.csv", "snapshot"]
)
async def test_graded_source_drift_is_rejected_before_rendering(tmp_path, name):
    case, grade = setup(tmp_path)
    source(tmp_path, name).write_bytes(b"changed after native check")
    renderer = Renderer()
    with pytest.raises(DomainError, match="RSI_ARTIFACT_EVIDENCE_CHANGED"):
        await collect_artifact_evidence(case, grade, tmp_path, renderer)
    assert renderer.calls == 0 and not (tmp_path / "artifact-evidence.json").exists()


@pytest.mark.parametrize("stage", [1, 2])
@pytest.mark.parametrize("name", ["stock_analysis.pptx", "stock_cleaned.csv", "snapshot"])
async def test_renderer_or_grounding_race_cannot_publish_a_mixed_version_pack(
    tmp_path, stage, name
):
    case, grade = setup(tmp_path)

    def mutate(call):
        if call == stage:
            source(tmp_path, name).write_bytes(b"concurrent source change")

    with pytest.raises(DomainError, match="RSI_ARTIFACT_EVIDENCE_CHANGED"):
        await collect_artifact_evidence(case, grade, tmp_path, Renderer(mutate))
    assert not (tmp_path / "artifact-evidence.json").exists()


@pytest.mark.parametrize(
    "fault",
    [
        "conflicting_alias",
        "conflicting_hash",
        "outside",
        "symlink",
        "missing_hash",
        "snapshot_alias",
    ],
)
def test_ambiguous_or_unbound_evidence_cannot_be_accepted(tmp_path, fault):
    case, grade = setup(tmp_path)
    entry = grade["evidence"][0]
    if fault == "conflicting_alias":
        entry["path"] = "stock_cleaned.csv"
    elif fault == "conflicting_hash":
        grade["evidence"].append({**entry, "sha256": "0" * 64})
    elif fault == "outside":
        entry["remote_path"] = "../outside"
    elif fault == "symlink":
        path = tmp_path / "stock-remote/stock_analysis.pptx"
        path.rename(path.with_suffix(".saved"))
        path.symlink_to(path.with_suffix(".saved").name)
    elif fault == "missing_hash":
        del entry["sha256"]
    else:
        grade["evidence"][-1]["remote_path"] = "stock_analysis.pptx"
    with pytest.raises(DomainError, match="RSI_ARTIFACT_EVIDENCE_CHANGED"):
        artifact_evidence.assert_review_sources(case, grade, tmp_path)


@pytest.mark.parametrize("name", ["stock_analysis.pptx", "stock_cleaned.csv", "snapshot"])
async def test_drift_during_paid_rating_stays_pending_without_replaying_models(tmp_path, name):
    case, grade = setup(tmp_path)
    calls = []

    class Model(ProtocolFixtureModel):
        async def stream(self, messages, tools):
            calls.append(self)
            if len(calls) == 2:
                source(tmp_path, name).write_bytes(b"changed during model review")
            async for event in super().stream(messages, tools):
                yield event

    judge = reviewer(lambda settings, role: Model([{"text": json.dumps(rating())}]))
    budget = judge.budget()
    result = await judge.review(case, grade, tmp_path, Renderer(), budget=budget, journal=[])
    assert len(calls) == 2
    assert result["pending"] and not result["passed"] and result["quality"] == 0
    assert result["reason"] == "RSI_ARTIFACT_EVIDENCE_CHANGED"
    assert result["native_partial"] == grade["native_partial"]
    record = json.loads((tmp_path / "artifact-review.json").read_text())
    assert record["error"] == result["reason"] and len(record["ratings"]) == 2
    assert (
        record["metrics"]["model_calls"] == 2 and record["metrics"]["token_coverage"] == "complete"
    )


def test_authored_path_evidence_is_still_checked(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "plan.md"
    path.write_text("original")
    case = {"judge": {"kind": "authored"}}
    grade = {"evidence": [{"path": "plan.md", "sha256": sha(path)}]}
    artifact_evidence.assert_review_sources(case, grade, tmp_path)
    path.write_text("changed")
    with pytest.raises(DomainError, match="RSI_ARTIFACT_EVIDENCE_CHANGED"):
        artifact_evidence.assert_review_sources(case, grade, tmp_path)
