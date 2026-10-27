"""LongMemEval-V2 textual retrieval with complete haystacks and a frozen native metric."""

import base64
import gzip
import hashlib
import io
import json
import re

from roami_agent.improvement.contracts import (
    DIMENSIONS,
    digest,
    freeze_suite,
    relative_file,
    require,
)
from roami_agent.improvement.grading import quality
from roami_agent.protocol.errors import DomainError

QUESTION_ID = "4ed01379"
EVAL_SPEC = "norm_phrase_set_match|lower=true|normalize_hyphen=true|strip_punct=true|separators=,;|require_non_empty=true"
MAX_HISTORY_BYTES = 180_000_000


def history_records(packed, expected):
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as archive:
        data = archive.read(MAX_HISTORY_BYTES + 1)
    require(len(data) <= MAX_HISTORY_BYTES, "RSI_INPUT_TOO_LARGE")
    records = json.loads(data)
    require(isinstance(records, list) and len(records) == 100, "RSI_FULL_HISTORY_REQUIRED")
    require([r.get("id") for r in records] == [r["id"] for r in expected], "RSI_SOURCE_CHANGED")
    for record, pin in zip(records, expected, strict=True):
        raw = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode()
        require(
            len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"],
            "RSI_SOURCE_CHANGED",
        )
    return records


def import_long_memory(questions, haystacks, trajectories, verifier, *, revision, code_revision):
    require(all(re.fullmatch(r"[a-f0-9]{40}", v) for v in (revision, code_revision)))
    questions_ = [json.loads(line) for line in questions.read_text().splitlines() if line.strip()]
    selected = [q for q in questions_ if q["id"] == QUESTION_ID]
    require(len(selected) == 1, "RSI_SOURCE_TASK_REQUIRED")
    question = selected[0]
    require(question["eval_function"] == EVAL_SPEC and question["image"] is None)
    ids = json.loads(haystacks.read_text())[QUESTION_ID]
    require(
        len(ids) == len(set(ids)) == 100
        and all(isinstance(i, str) and re.fullmatch(r"[a-f0-9]{8}", i) for i in ids),
        "RSI_FULL_HISTORY_REQUIRED",
    )
    selected_records, seen, checksum = {}, set(), hashlib.sha256()
    with trajectories.open("rb") as source:
        for line in source:
            checksum.update(line)
            require(len(line) <= 20_000_000, "RSI_INPUT_TOO_LARGE")
            record = json.loads(line)
            identifier = record["id"]
            require(identifier not in seen, "RSI_DUPLICATE_SOURCE_ID")
            seen.add(identifier)
            if identifier in ids:
                require(record.get("domain") == "enterprise")
                states = record.get("states")
                require(
                    isinstance(states, list)
                    and 1 <= len(states) <= 2000
                    and [s.get("state_index") for s in states] == list(range(len(states)))
                    and all(isinstance(s.get("accessibility_tree"), str) for s in states),
                    "RSI_HISTORY_STATE_REQUIRED",
                )
                selected_records[identifier] = record
    require(set(selected_records) == set(ids), "RSI_FULL_HISTORY_REQUIRED")
    records = [selected_records[i] for i in ids]
    raw = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode()
    require(len(raw) <= MAX_HISTORY_BYTES, "RSI_INPUT_TOO_LARGE")
    packed = gzip.compress(raw, mtime=0)
    require(len(packed) <= 48_000_000, "RSI_INPUT_TOO_LARGE")
    pins = []
    for record in records:
        data = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode()
        pins.append(
            {"id": record["id"], "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )
    assets = {
        f"history-{start // 8_000_000:03}.part": base64.b64encode(
            packed[start : start + 8_000_000]
        ).decode()
        for start in range(0, len(packed), 8_000_000)
    }
    metric = verifier.read_text()
    case = {
        "id": "longmemeval-v2:" + QUESTION_ID,
        "category": "LAB",
        "layer": "public_component",
        "split": "public_test",
        "cluster": "longmemeval-v2:enterprise:static-environment:" + QUESTION_ID,
        "counts_as_delivery": True,
        "grading_profile": "research",
        "prompt": question["question"]
        + "\n\nThis is an offline textual-history retrieval adaptation. All 100 trajectories from the original small haystack are in /workspace/history; history-index.json preserves their original order. Original accessibility trees, actions and thoughts are available; screenshot paths are metadata only and images are not supplied. Search the history without assuming a live ServiceNow instance. Save the boxed final answer to /workspace/answer.txt and cite the supporting history in /workspace/evidence.json as a non-empty JSON array of {trajectory_id, state_index, quote}, using exact accessibility-tree quotes (20–500 characters). Use 1–10 citations and include the email action on the relevant form. Do not edit the input history. The original native metric runs after exit; RSI also rejects extra or contradictory final-answer phrases and invalid citations. This does not measure memory ingestion, persisted learning, multimodal retrieval or official leaderboard latency.",
        "files": {},
        "asset_files": assets,
        "limits": {"seconds": 900, "tokens": 192000, "requests": 40},
        "judge": {
            "kind": "long_memory",
            "question_id": QUESTION_ID,
            "expected": question["answer"],
            "eval_spec": EVAL_SPEC,
            "verifier": metric,
            "history_parts": sorted(assets),
            "packed_sha256": hashlib.sha256(packed).hexdigest(),
            "records": pins,
        },
        "origin": {
            "benchmark": "longmemeval_v2",
            "task_id": QUESTION_ID,
            "revision": revision,
            "code_revision": code_revision,
            "source_split": "small:enterprise:static-environment",
            "input_sha256": digest({"question": question["question"], "records": pins}),
            "source_trajectories_sha256": checksum.hexdigest(),
            "verifier_sha256": hashlib.sha256(metric.encode()).hexdigest(),
            "adapter_revision": "textual-complete-small-haystack-v1",
            "adapted": True,
            "adaptation": "All100 original small-tier textual trajectories and original deterministic metric; no screenshots, memory ingestion, persisted learning or official latency comparison. Added exact final-answer and citation-integrity gates.",
        },
    }
    return freeze_suite(
        "longmemeval-v2-" + QUESTION_ID + "-textual-v1",
        [case],
        official_leaderboard_comparable=False,
    )


def prepare_history(case, workspace):
    spec = case["judge"]
    packed = b"".join(
        base64.b64decode(case["asset_files"][p], validate=True) for p in spec["history_parts"]
    )
    require(hashlib.sha256(packed).hexdigest() == spec["packed_sha256"], "RSI_SOURCE_CHANGED")
    records = history_records(packed, spec["records"])
    directory = workspace / "history"
    directory.mkdir(mode=0o700)
    for record in records:
        path = directory / (record["id"] + ".json")
        with path.open("x") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        path.chmod(0o600)
    (workspace / "history-index.json").write_text(
        json.dumps({"trajectory_ids": [r["id"] for r in records]})
    )
    (workspace / "history-index.json").chmod(0o600)
    for name in spec["history_parts"]:
        relative_file(workspace, name).unlink()


PROGRAM = r"""import hashlib,json,pathlib,re,sys
def user_email_action(tree,quote):
 if 'Send an email to this address' not in quote:return False
 roots=[]
 for line in tree.splitlines():
  if not line.strip():continue
  depth=len(line)-len(line.lstrip())
  while roots and depth<=roots[-1][0]:roots.pop()
  root=re.match(r"(?:\[[^\]\n]+\]\s*)?RootWebArea '([^'\n]*)'",line.lstrip())
  if root:roots.append((depth,bool(re.search(r'\|\s*user\s*\|',root[1],re.I))))
  if roots and roots[-1][1] and "button 'Send an email to this address'" in line:return True
 return False
payload=json.loads(sys.stdin.read());spec=payload['spec'];ns={'__name__':'frozen_longmem_metric'}
exec(compile(spec['verifier'],'frozen_qa_eval_metrics.py','exec'),ns)
root=pathlib.Path('/workspace');checks={};sources={}
checks['history_inventory']={p.name for p in (root/'history').iterdir()}=={p['id']+'.json' for p in spec['records']}
try:
 index=root/'history-index.json'
 checks['history_order_unchanged']=not index.is_symlink() and index.stat().st_size<16000 and json.loads(index.read_text())=={'trajectory_ids':[p['id'] for p in spec['records']]}
except (OSError,ValueError):checks['history_order_unchanged']=False
for pin in spec['records']:
 path=root/'history'/(pin['id']+'.json')
 if path.is_symlink() or not path.is_file() or path.stat().st_size!=pin['bytes']:
  checks['history_unchanged']=False;break
 raw=path.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=pin['sha256']:
  checks['history_unchanged']=False;break
 sources[pin['id']]=json.loads(raw)
else:checks['history_unchanged']=True
answer=payload['answer'];match=re.fullmatch(r'\s*\\boxed\{([^{}]+)\}\s*',answer)
checks['boxed_final_answer']=match is not None
parsed=ns['extract_boxed_answer'](answer)
native=bool(ns['eval_from_spec'](spec['eval_spec'],parsed,spec['expected']))
checks['native_metric']=native
checks['exact_final_phrases']=ns['normalize_phrase'](parsed)==ns['normalize_phrase'](spec['expected'])
evidence=payload['evidence'];citations=isinstance(evidence,list) and 1<=len(evidence)<=10;affordance=False
if citations:
 for ref in evidence:
  if not isinstance(ref,dict) or set(ref)!={'trajectory_id','state_index','quote'}:citations=False;break
  trajectory=sources.get(ref['trajectory_id']);index=ref['state_index'];quote=ref['quote']
  if trajectory is None or type(index) is not int or not 0<=index<len(trajectory['states']) or not isinstance(quote,str) or not 20<=len(quote)<=500:citations=False;break
  tree=trajectory['states'][index]['accessibility_tree']
  if quote not in tree:citations=False;break
  if user_email_action(tree,quote):affordance=True
checks['valid_source_citations']=citations
checks['cited_affordance']=citations and affordance
print(json.dumps({'checks':checks,'native_metric':float(native)}))
"""


async def grade_long_memory(case, workspace, executor):
    evidence, checks, metric = [], {}, 0.0
    try:
        answer = relative_file(workspace, "answer.txt")
        citations = relative_file(workspace, "evidence.json")
        require(answer.is_file() and answer.stat().st_size <= 4000)
        require(citations.is_file() and citations.stat().st_size <= 16000)
        data = {
            "spec": case["judge"],
            "answer": answer.read_text(),
            "evidence": json.loads(citations.read_text()),
        }
        result = json.loads(
            (
                await executor.sandbox(
                    workspace, PROGRAM, input=json.dumps(data).encode(), timeout=90
                )
            )
            .decode()
            .splitlines()[-1]
        )
        checks, metric = result["checks"], result["native_metric"]
        evidence = [
            {"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in [answer, citations]
        ]
    except (DomainError, ValueError, OSError, UnicodeError, KeyError, TypeError):
        checks["verification_completed"] = False
    passed = bool(checks) and all(checks.values())
    return {
        **quality(
            dict.fromkeys(DIMENSIONS, 3 if passed else 0),
            case.get("grading_profile", "research"),
            hard_passed=passed,
        ),
        "checks": checks,
        "native_metric": metric,
        "grade_scope": "complete_textual_haystack_retrieval_not_persisted_memory",
        "evidence": evidence,
        "artifact_hash": digest(evidence),
        "reason": "assertions_passed" if passed else "assertion_failed",
    }
