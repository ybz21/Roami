"""Materialize the agreed authored suite without publishing private evaluation inputs."""

import json
import secrets
from pathlib import Path

from roami_agent.improvement.authored_fixtures import recipe
from roami_agent.improvement.contracts import digest, freeze_suite
from roami_agent.improvement.executors import private_json
from roami_agent.improvement.mechanisms import nodes


def authored_suite(seed):
    specs = json.loads(Path(__file__).with_name("case_specs.json").read_text())
    cases = []
    limits = {
        "simple": {"seconds": 60, "tokens": 32000, "requests": 8},
        "standard": {"seconds": 300, "tokens": 128000, "requests": 24},
        "long": {"seconds": 900, "tokens": 384000, "requests": 64},
    }
    for spec in specs:
        case = {
            "id": spec["id"],
            "category": spec["category"],
            "layer": "mechanism" if spec["kind"] == "mechanism_regression" else "authored_real",
            "split": "development",
            "prompt": spec["prompt"] + "\n已知条件：" + spec["preconditions"],
            "counts_as_delivery": spec["counts_as_delivery"],
            "limits": limits[spec["limit_profile"]],
            "grading_profile": spec["grading_profile"],
            "cluster": "roami:" + spec["id"],
            "decision_domains": spec["decision_domains"],
            "files": {},
            "origin": {
                "kind": "roami_authored",
                "recipe_revision": "authored-v8-csv-request-identity"
                if spec["id"] == "DEMO-02"
                else "authored-v9-stock-evidence-contract"
                if spec["id"] in {"STOCK-01", "STOCK-03"}
                else "authored-v7",
            },
        }
        if case["layer"] == "mechanism":
            case.update(
                judge={"kind": "mechanism", "selectors": nodes(spec["id"])},
                adaptation={
                    "kind": "runtime_regression_variant",
                    "source_contract": spec["id"],
                    "scope": "Subsystem invariant checks with scripted providers, not live-model decision quality.",
                    "fixtures": "Repository regression data; canonical numeric values may differ.",
                },
            )
            case["limits"] = {"seconds": 120, "tokens": 32000, "requests": 8}
        else:
            data = recipe(spec["id"], seed)
            case.update(
                {k: v for k, v in data.items() if k not in {"prompt_suffix", "contract_revision"}}
            )
            if data["contract_revision"]:
                case["origin"]["recipe_revision"] = data["contract_revision"]
            case["prompt"] += data["prompt_suffix"]
        cases.append(case)
    return freeze_suite(
        "roami-authored-40-v11",
        cases,
        fixture_seed_hash=digest(seed),
        composition={"authored_real": 20, "mechanism_regression_variants": 20},
    )


def prepare_corpus(service, owner):
    root = service.ledger.path.parent / "corpus"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / "authored-40-v11.json"
    if not path.exists():
        private_json(path, authored_suite(secrets.token_hex(24)))
    summary = service.control.register_suite(owner, path)
    return {
        "suite": summary,
        "public_tasks_imported": 0,
        "note": "Public and private packs are registered independently.",
    }
