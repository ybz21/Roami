"""Frozen company leadership workflow with native state evidence and separate quality review."""

import ast
import base64
import hashlib
import json
import re

from roami_agent.improvement.company_environment import IMAGE_RE
from roami_agent.improvement.contracts import (
    DIMENSIONS,
    digest,
    freeze_suite,
    relative_file,
    require,
)
from roami_agent.improvement.grading import quality
from roami_agent.protocol.errors import DomainError

TASK_ID = "hr-make-slides-introduce-leadership"


def import_company(source_dir, snapshot, *, images, revision, snapshot_revision):
    require(re.fullmatch(r"[a-f0-9]{40}", revision))
    require(isinstance(snapshot_revision, str) and 0 < len(snapshot_revision) <= 200)
    require(isinstance(images, dict) and set(images) == set(IMAGE_RE))
    require(
        all(
            isinstance(images[k], str) and re.fullmatch(pattern, images[k])
            for k, pattern in IMAGE_RE.items()
        )
    )
    data = snapshot.read_bytes()
    require(0 < len(data) <= 4_000_000, "RSI_INPUT_TOO_LARGE")
    task = source_dir / "workspaces" / "tasks" / TASK_ID
    instruction = (task / "task.md").read_text()
    verifier = (task / "evaluator.py").read_text()
    common = (source_dir / "common.py").read_text()
    parsed = ast.parse(common)
    helpers = "\n\n".join(
        ast.get_source_segment(common, node)
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in {"grader", "get_all_texts_from_slide"}
    )
    require("def grader(" in helpers and "def get_all_texts_from_slide(" in helpers)
    scoring = (source_dir / "scoring.py").read_text()
    case = {
        "id": "the-agent-company:" + TASK_ID,
        "category": "DOC",
        "layer": "public_component",
        "split": "public_test",
        "cluster": "the-agent-company:leadership-workflow",
        "counts_as_delivery": True,
        "grading_profile": "presentation",
        "files": {},
        "prompt": instruction
        + "\n\nThis trial has an isolated native RocketChat 5.3 service restored from the benchmark snapshot; the agent container has no direct network access. Use python /workspace/company-http.py GET|POST /api/v1/path [JSON] for the authenticated benchmark account. API routes: users.list (exact-name or username query), users.info, im.list, im.history, im.create {username}, chat.postMessage {roomId,text}. Tokens stay on the host. Discover leadership profiles from the native directory; do not assume names or biographies. Save the presentation in /workspace/leadership_intro.pptx and notify the HR manager in this trial. Do not include URLs in messages. Unknown writes must be reconciled by reading, never replayed. Directory changes and service administration are unavailable. Native checkpoint results and current-trial notification evidence are graded independently after exit; biography truth and visual usability await calibrated artifact review. This adaptation does not measure browser interaction or NPC dialogue.",
        "limits": {"seconds": 900, "tokens": 256000, "requests": 48},
        "judge": {
            "kind": "company",
            "task_id": TASK_ID,
            "images": images,
            "db_dump": base64.b64encode(data).decode(),
            "db_sha256": hashlib.sha256(data).hexdigest(),
            "verifier": verifier,
            "common_helpers": helpers,
            "scoring": scoring,
            "rubric_required": True,
        },
        "origin": {
            "benchmark": "the_agent_company",
            "task_id": TASK_ID,
            "revision": revision,
            "source_split": "company_hr_workflow",
            "adapter_revision": "native-rocketchat-with-post-exit-snapshot-v1",
            "snapshot_revision": snapshot_revision,
            "snapshot_sha256": hashlib.sha256(data).hexdigest(),
            "verifier_sha256": hashlib.sha256(verifier.encode()).hexdigest(),
            "input_sha256": digest(
                {
                    "instruction": instruction,
                    "db_sha256": hashlib.sha256(data).hexdigest(),
                    "images": images,
                }
            ),
            "adapted": True,
            "adaptation": "Native RocketChat5.3 and Mongo5 services, pinned snapshot restored per trial, internal unpublished network, authenticated allowlisted Unix-socket API bridge. Original5 checkpoint predicates/scoring are retained; transport reads a post-exit native snapshot using correct direct-room lookup. Added new-notification and unchanged-directory gates. Browser/NPC interaction excluded; biography/visual quality remains pending calibrated review.",
        },
    }
    return freeze_suite(
        "the-agent-company-leadership-native-v1", [case], official_leaderboard_comparable=False
    )


PROGRAM = r"""import functools,hashlib,json,logging,pathlib,re,sys,types
payload=json.loads(sys.stdin.read());spec=payload['spec'];state=payload['state'];initial=state['initial'];final=state['final']
scoring=types.ModuleType('scoring');sys.modules['scoring']=scoring;exec(compile(spec['scoring'],'frozen_scoring.py','exec'),scoring.__dict__)
common=types.ModuleType('common');sys.modules['common']=common
common.__dict__.update(functools=functools,logging=logging)
exec(compile(spec['common_helpers'],'frozen_common.py','exec'),common.__dict__)
def histories(name):
 target=next((u for u in final['users'] if name.lower() in {u.get('name','').lower(),u.get('nameInsensitive','').lower(),u.get('username','').lower()}),None)
 if target is None:return []
 actor=final['actor_id'];rooms=[r for r in final['rooms'] if set(r.get('uids',[]))=={actor,target['_id']}]
 return [m for r in rooms for m in final['messages'].get(r['_id'],[])]
common.create_rocketchat_client=lambda:final
common.get_rocketchat_personal_chat_history=lambda client,name:[m.get('msg','') for m in histories(name)][::-1]
namespace={'__name__':'frozen_company_evaluator'};exec(compile(spec['verifier'],'frozen_evaluator.py','exec'),namespace)
result=namespace['grade_checkpoints']().to_dict();checks={'native_checkpoints':result['final_score']=={'total':5,'result':5}}
old_ids={m['_id'] for messages in initial['messages'].values() for m in messages}
new=[m for m in histories('Chen Xinyi') if m['_id'] not in old_ids and m.get('u',{}).get('_id')==final['actor_id']]
checks['new_hr_notification']=any(re.search(r'\b(done|completed?|finished)\b|完成',m.get('msg',''),re.I) for m in new)
def directory(users):
 return sorted([{k:v for k,v in user.items() if k in {'_id','name','username','nameInsensitive','bio','customFields'}} for user in users],key=lambda u:u['_id'])
checks['directory_unchanged']=directory(initial['users'])==directory(final['users'])
print(json.dumps({'native':result,'checks':checks,'new_notification_ids':[m['_id'] for m in new]}))
"""


async def grade_company(case, workspace, executor, *, state_path):
    checks, evidence, native = {}, [], 0
    try:
        require(
            state_path.is_file()
            and not state_path.is_symlink()
            and state_path.stat().st_size <= 2_000_000,
            "RSI_COMPANY_SNAPSHOT_FAILED",
        )
        state = json.loads(state_path.read_text())
        deck = relative_file(workspace, "leadership_intro.pptx")
        require(deck.is_file() and deck.stat().st_size <= 32_000_000)
        result = json.loads(
            (
                await executor.sandbox(
                    workspace,
                    PROGRAM,
                    input=json.dumps({"spec": case["judge"], "state": state}).encode(),
                    timeout=90,
                )
            )
            .decode()
            .splitlines()[-1]
        )
        checks = result["checks"]
        native = result["native"]["final_score"]["result"] / 5
        evidence = [
            {
                "path": "leadership_intro.pptx",
                "sha256": hashlib.sha256(deck.read_bytes()).hexdigest(),
            },
            {
                "source": "host_native_snapshot",
                "sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
            },
            {
                "native_checkpoints": result["native"],
                "new_notification_ids": result["new_notification_ids"],
            },
        ]
    except (DomainError, OSError, ValueError, KeyError, TypeError):
        checks["verification_completed"] = False
    hard = bool(checks) and all(checks.values())
    grade = quality(
        dict.fromkeys(DIMENSIONS, 3 if hard else 0), "presentation", hard_passed=hard, pending=hard
    )
    grade.update(
        quality=0,
        checks=checks,
        native_metric=native,
        evidence=evidence,
        artifact_hash=digest(evidence),
        rubric_required=True,
        grade_scope="native_company_checkpoints_biography_and_visual_quality_pending",
        reason="independent_rubric_required" if hard else "hard_assertion_failed",
    )
    return grade
