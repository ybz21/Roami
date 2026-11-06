import copy
import hashlib
import io
import json
import runpy
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

SCRIPT = (
    Path(__file__).parents[2]
    / "skills/okr-development/parts/connectors/bilibili/scripts/bilibili.py"
)
skill = SimpleNamespace(**runpy.run_path(str(SCRIPT), run_name="bilibili_skill_test"))
BVID = "BV1abcdefghj"


class Response:
    status = 200

    def __init__(self, raw):
        self.raw = raw
        self.headers = {"Date": "Fri, 06 Nov 2026 00:00:00 GMT", "Set-Cookie": "private"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.raw[:limit]


def raw_response():
    return (
        " \n"
        + json.dumps(
            {
                "code": 0,
                "data": {
                    "bvid": BVID,
                    "aid": 42,
                    "state": 0,
                    "owner": {"mid": 24},
                    "stat": {"aid": 42, "view": 7, "like": 0, "reply": 0},
                },
            },
            indent=2,
        )
        + "\n "
    ).encode()


def collect(raw=None, status=200):
    response = Response(raw if raw is not None else raw_response())
    response.status = status
    with patch.object(skill.urllib.request, "build_opener") as opener:
        opener.return_value.open.return_value = response
        candidate = skill.collect(BVID, 24, "Asia/Shanghai")
    return candidate, opener


def workspace():
    return {
        "revision": 31,
        "projectFiles": {"connectorSkillBatches": True},
        "connectors": [
            {
                "id": "video-public",
                "service": "bilibili",
                "identity": f"bilibili:24:{BVID}",
                "timezone": "Asia/Shanghai",
                "window": "snapshot",
                "packageSha256": "a" * 64,
                "bindings": [
                    {"metricId": field, "field": field}
                    for field in ["view", "like", "reply", "favorite"]
                ],
            }
        ],
        "metrics": [
            {"id": field, "source": "manual", "unit": "次"}
            for field in ["view", "like", "reply", "favorite"]
        ],
    }


def prepare(ws=None, candidate=None):
    return skill.prepare(
        ws if ws is not None else workspace(),
        candidate if candidate is not None else collect()[0],
        "video-public",
        "b" * 32,
        "delivery/response.raw.json",
    )


def test_fetch_preserves_original_bytes_zeros_and_unknowns():
    candidate, opener = collect()
    retained = json.loads(json.dumps(candidate))["evidence"]["http"]["body"].encode()
    assert retained == raw_response()
    assert candidate["evidence"]["sha256"] == hashlib.sha256(retained).hexdigest()
    assert candidate["values"] == {"view": 7, "like": 0, "reply": 0}
    assert "favorite" not in candidate["values"]
    assert candidate["evidence"]["http"]["headers"] == {"Date": Response(b"").headers["Date"]}
    request = opener.return_value.open.call_args.args[0]
    assert request.full_url == "https://api.bilibili.com/x/web-interface/view?bvid=" + BVID
    assert not request.has_header("Cookie")
    assert opener.return_value.open.call_args.kwargs == {"timeout": 15}
    assert opener.return_value.open.call_count == 1


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("code",), -412),
        (("code",), False),
        (("data", "bvid"), "BV1XXXXXXXXX"),
        (("data", "owner", "mid"), 25),
        (("data", "owner", "mid"), True),
        (("data", "state"), -4),
        (("data", "state"), False),
        (("data", "aid"), True),
        (("data", "stat", "aid"), 43),
        (("data", "stat", "view"), True),
        (("data", "stat", "view"), -1),
        (("data", "stat", "view"), "7"),
        (("data", "stat", "view"), 9007199254740992),
        (("data", "stat"), {}),
    ],
)
def test_fetch_rejects_wrong_identity_api_failure_and_invalid_values(path, value):
    payload = json.loads(raw_response())
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        collect(json.dumps(payload).encode())


def test_fetch_rejects_large_response_non_200_and_redirect():
    with pytest.raises(ValueError, match="exceeds limit"):
        collect(b"x" * (skill.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="HTTP 200"):
        collect(status=429)
    with pytest.raises(ValueError, match="reconciliation"):
        skill.NoRedirect().redirect_request(None, None, 302, "moved", {}, "https://elsewhere")


@pytest.mark.parametrize(("bvid", "mid"), [("../video", 24), (BVID, True), (BVID, 0)])
def test_invalid_identity_stops_before_network(bvid, mid):
    with patch.object(skill.urllib.request, "build_opener") as network:
        with pytest.raises(ValueError):
            skill.collect(bvid, mid, "Asia/Shanghai")
        network.assert_not_called()


def test_prepare_uses_confirmed_mapping_omits_missing_and_never_publishes():
    candidate, _ = collect()
    candidate["capturedAt"] = "2026-11-05T16:30:00Z"
    candidate["asOf"] = "2026-11-06"
    request, raw = prepare(candidate=candidate)
    assert raw == raw_response()
    assert request["revision"] == 31
    batch = request["batch"]
    assert batch["sourceIdentity"] == f"bilibili:24:{BVID}"
    assert batch["values"] == [
        {"metricId": "view", "unit": "次", "value": 7},
        {"metricId": "like", "unit": "次", "value": 0},
        {"metricId": "reply", "unit": "次", "value": 0},
    ]
    assert batch["windowStart"] == batch["windowEnd"] == candidate["capturedAt"]
    assert batch["evidence"][0]["sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("source", "ownerMid"), 25),
        (("source", "aid"), 43),
        (("source", "identity"), "another-account"),
        (("evidence", "sha256"), "0" * 64),
        (("evidence", "http", "body"), "{}"),
        (("evidence", "payload"), {}),
        (("evidence", "http", "status"), 304),
        (("values", "view"), 8),
        (("values", "like"), False),
        (("capturedAt",), "2026-11-06T00:00:00"),
        (("asOf",), "1999-01-01"),
    ],
)
def test_prepare_rejects_tampered_evidence_identity_and_date(path, value):
    candidate, _ = collect()
    target = candidate
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        prepare(candidate=candidate)


@pytest.mark.parametrize(
    ("key", "value"),
    [("service", "mcp"), ("identity", "other"), ("window", "day"), ("packageSha256", "")],
)
def test_prepare_rejects_changed_source_contract(key, value):
    ws = workspace()
    ws["connectors"][0][key] = value
    with pytest.raises(ValueError):
        prepare(ws=ws)


def test_prepare_requires_capability_and_unambiguous_metrics():
    ws = workspace()
    ws["projectFiles"]["connectorSkillBatches"] = False
    with pytest.raises(ValueError, match="support"):
        prepare(ws=ws)
    ws = workspace()
    ws["connectors"][0]["bindings"].append(copy.deepcopy(ws["connectors"][0]["bindings"][0]))
    with pytest.raises(ValueError, match="mapping"):
        prepare(ws=ws)
    ws = workspace()
    ws["connectors"][0]["bindings"] = [{"metricId": "view", "field": "completion"}]
    with pytest.raises(ValueError, match="mapping"):
        prepare(ws=ws)


def test_cli_prepare_is_offline_and_replay_preserves_original_files(tmp_path):
    ws, candidate, output = tmp_path / "ws.json", tmp_path / "candidate.json", io.StringIO()
    ws.write_text(json.dumps(workspace()))
    candidate.write_text(json.dumps(collect()[0]))
    argv = [str(SCRIPT), "prepare", "--workspace", str(ws), "--candidate", str(candidate)]
    for key, value in {
        "connector": "video-public",
        "batch-id": "b" * 32,
        "project": str(tmp_path),
        "evidence": "delivery/raw.json",
        "output": "delivery/request.json",
    }.items():
        argv.extend(["--" + key, value])
    with (
        patch("sys.argv", argv),
        patch.object(skill.urllib.request, "build_opener") as network,
        redirect_stdout(output),
    ):
        assert skill.main() == 0
        original = (tmp_path / "delivery/request.json").read_bytes()
        assert skill.main() == 0
        assert (tmp_path / "delivery/request.json").read_bytes() == original
        assert (tmp_path / "delivery/raw.json").read_bytes() == raw_response()
        network.assert_not_called()
    with pytest.raises(ValueError, match="reconcile"):
        skill.write_once(tmp_path / "delivery/request.json", b"replacement")
    for name in ["../outside", "/absolute", "a/./b", "a//b", "a%2fb", "a\\b"]:
        with pytest.raises(ValueError):
            skill.destination(tmp_path, name)
    (tmp_path / "link").symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        skill.destination(tmp_path, "link/outside")


def test_fetch_failure_keeps_stdout_empty():
    out, err = io.StringIO(), io.StringIO()
    with (
        patch(
            "sys.argv",
            [
                str(SCRIPT),
                "fetch",
                "--bvid",
                BVID,
                "--owner-mid",
                "24",
                "--timezone",
                "Asia/Shanghai",
            ],
        ),
        patch.object(skill.urllib.request, "build_opener", side_effect=TimeoutError("deadline")),
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        assert skill.main() == 1
    assert out.getvalue() == ""
    assert "deadline" in err.getvalue()
