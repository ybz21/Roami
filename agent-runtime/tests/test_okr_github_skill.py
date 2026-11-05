import hashlib
import io
import json
import runpy
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PATH = (
    Path(__file__).parents[2]
    / "skills/okr-development/parts/connectors/github/scripts/fetch_github.py"
)
module = SimpleNamespace(**runpy.run_path(str(PATH), run_name="github_skill_test"))


class Response:
    def __init__(self, raw, status=200):
        self.raw = raw
        self.status = status
        self.headers = {
            "Date": "Fri, 06 Nov 2026 00:00:00 GMT",
            "X-GitHub-Request-Id": "fixture",
            "Set-Cookie": "must-not-export",
        }

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return self.raw[:size]


class Opener:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        return self.response


class EvidenceTests(unittest.TestCase):
    def raw(self, **changes):
        p = {"id": 42, "full_name": "example/project", "stargazers_count": 11, "forks_count": 5}
        p.update(changes)
        return (" \n" + json.dumps(p, indent=2) + "\n ").encode()

    def collect(self, raw=None, status=200, expected=42):
        opener = Opener(Response(raw if raw is not None else self.raw(), status))
        with patch.object(module.urllib.request, "build_opener", return_value=opener):
            result = module.collect("example/project", "Asia/Shanghai", expected)
        return result, opener

    def test_original_bytes_survive_json_transport(self):
        raw = self.raw()
        result, opener = self.collect(raw)
        wire = json.loads(json.dumps(result))
        retained = wire["evidence"]["http"]["body"].encode("utf-8")
        self.assertEqual(retained, raw)
        self.assertEqual(hashlib.sha256(retained).hexdigest(), wire["evidence"]["sha256"])
        self.assertNotEqual(
            hashlib.sha256(json.dumps(wire["evidence"]["payload"]).encode()).hexdigest(),
            wire["evidence"]["sha256"],
        )
        self.assertTrue(result["candidateOnly"])
        self.assertEqual(result["values"], {"stars": 11, "forks": 5})
        self.assertEqual(
            result["evidence"]["http"]["headers"],
            {"Date": "Fri, 06 Nov 2026 00:00:00 GMT", "X-GitHub-Request-Id": "fixture"},
        )
        request, timeout = opener.calls[0]
        self.assertEqual(request.full_url, "https://api.github.com/repos/example/project")
        self.assertEqual(timeout, 15)

    def test_recreated_repository_rejected(self):
        with self.assertRaisesRegex(ValueError, "Repository ID changed"):
            self.collect(self.raw(id=2))

    def test_foreign_repository_rejected(self):
        with self.assertRaisesRegex(ValueError, "identity or counts"):
            self.collect(self.raw(full_name="other/repo"))

    def test_boolean_and_negative_counts_rejected(self):
        for value in [True, -1, "11"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.collect(self.raw(stargazers_count=value))

    def test_non_200_rejected(self):
        with self.assertRaisesRegex(ValueError, "HTTP 200"):
            self.collect(status=304)

    def test_large_body_rejected(self):
        with self.assertRaisesRegex(ValueError, "exceeds limit"):
            self.collect(b"x" * 1048577)

    def test_invalid_expected_id_rejected_before_fetch(self):
        with patch.object(module.urllib.request, "build_opener") as network:
            for expected in [0, -1, True]:
                with self.subTest(expected=expected), self.assertRaises(ValueError):
                    module.collect("example/project", "Asia/Shanghai", expected)
            network.assert_not_called()

    def test_redirect_requires_reconciliation(self):
        with self.assertRaisesRegex(ValueError, "source reconciliation"):
            module.NoRedirect().redirect_request(
                None, None, 301, "moved", {}, "https://other.invalid/repo"
            )

    def test_cli_checks_the_expected_id_before_emitting_a_candidate(self):
        output, error = io.StringIO(), io.StringIO()
        opener = Opener(Response(self.raw(id=43)))
        with (
            patch.object(module.urllib.request, "build_opener", return_value=opener),
            patch(
                "sys.argv",
                ["fetch_github.py", "--repo", "example/project", "--repository-id", "42"],
            ),
            redirect_stdout(output),
            redirect_stderr(error),
        ):
            self.assertEqual(module.main(), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Repository ID changed", error.getvalue())

    def test_cli_read_timeout_keeps_stdout_empty(self):
        output, error = io.StringIO(), io.StringIO()
        response = Response(self.raw())
        with (
            patch.object(response, "read", side_effect=TimeoutError("read deadline")),
            patch.object(module.urllib.request, "build_opener", return_value=Opener(response)),
            patch("sys.argv", ["fetch_github.py", "--repo", "example/project"]),
            redirect_stdout(output),
            redirect_stderr(error),
        ):
            self.assertEqual(module.main(), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("read deadline", error.getvalue())

    def test_initial_discovery_can_return_an_unconfirmed_id(self):
        result, _ = self.collect(expected=None)
        self.assertTrue(result["candidateOnly"])
        self.assertEqual(result["source"]["repositoryId"], 42)
