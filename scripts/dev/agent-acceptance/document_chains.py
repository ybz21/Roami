"""Sources and behavioral checks for research-to-document dialogue cases."""

import hashlib
import json
import re
from urllib.parse import urldefrag, urlparse


def seed_document_sources(instance):
    pages = instance.root / "web-fixture"
    documents = {
        "search.html": '<h1>供应商资料检索</h1><p>关键词：供应商、价格、服务指标、更正、SLA。</p><a href="alpha.html">Alpha服务说明</a><a href="beta.html">Beta服务说明</a><a href="price-update.html">Alpha价格更正</a><a href="sla.html">验收规则</a>',
        "alpha.html": '<h1>Alpha服务说明</h1><p>发布日期2026-10-01。月费80元，服务可用性99.9%，支持工单响应。</p><p>价格如有更正，以后续价格公告为准。</p><a href="price-update.html">最新价格公告</a>',
        "beta.html": "<h1>Beta服务说明</h1><p>发布日期2026-10-02。月费95元，服务可用性99.95%，支持工单响应。</p>",
        "price-update.html": "<h1>Alpha价格更正</h1><p>生效日期2026-10-15。Alpha月费从80元更正为88元；可用性99.9%保持不变。此公告覆盖此前价格。</p>",
        "sla.html": "<h1>SLA验收规则</h1><p>有效规则：将全部批次成功次数合计除以全部请求次数合计，再乘100%。不得直接平均各批次百分比。合格线为99%，最低需要的成功数向上取整。</p>",
    }
    for name, body in documents.items():
        (pages / name).write_text(
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            + body
            + "</html>"
        )


def validate_document_chain(instance, case, cid, answer, result):
    spec = case["document"]
    directory = instance.root / "workspaces" / case["id"]
    path = directory / spec["name"]
    assert path.is_file(), "Requested document was not written"
    assert path.resolve().is_relative_to(directory.resolve()), (
        "Document escaped the requested directory"
    )
    body = path.read_bytes()
    text = body.decode("utf-8")
    assert len(text.strip()) >= 180, (
        "Document is only an acknowledgement or a placeholder"
    )
    for word in spec.get("contains", []):
        assert word.casefold() in text.casefold(), (
            "Document missing required fact/section: " + word
        )
    links = re.findall(r'https?://[^\s<>"\)\]]+', text)
    cited = {urldefrag(link.rstrip("。，；;"))[0] for link in links}
    observations = instance.db(
        "SELECT o.body_json FROM resource_observations o JOIN tasks t ON t.id=o.task_id WHERE t.origin_conversation_id=?",
        (cid,),
    )
    observed = {
        urldefrag(json.loads(row["body_json"]).get("url", ""))[0]
        for row in observations
    }
    calls = execution_calls(instance, cid)
    assert not any(call["tool_name"] == "ask_user" for call in calls), (
        "Fully specified workflow asked for unnecessary confirmation"
    )
    successful = [
        call
        for call in calls
        if call["state"] == "succeeded" and tool_result(call).get("exitCode", 0) == 0
    ]
    for call in successful:
        args = json.loads(call["arguments_json"])
        output = tool_result(call)
        command = str(args.get("command", "")) + " " + " ".join(args.get("argv", []))
        if (
            call["tool_name"] in {"bash", "shell"}
            and output.get("exitCode") == 0
            and any(
                word in command
                for word in ["curl", "wget", "urllib.request", "requests.get"]
            )
        ):
            observed.update(
                urldefrag(url.rstrip("'\".,;"))[0]
                for url in re.findall(r"https?://[^\s'\"<>\]\)]+", command)
            )
    verified = cited & observed
    assert len(verified) >= spec.get("minSources", 1), (
        "Citations lack actual browser or successful HTTP-tool evidence"
    )
    for host in spec.get("sourceHosts", []):
        assert any(
            (urlparse(url).hostname or "").removeprefix("www.")
            == host.removeprefix("www.")
            for url in verified
        ), "No observed primary source from " + host
    for suffix in spec.get("sourceSuffixes", []):
        assert any(urlparse(url).path.endswith(suffix) for url in verified), (
            "No observed evidence for " + suffix
        )
    if spec.get("publicSearch"):
        assert any(
            urlparse(url).hostname
            in {
                "www.google.com",
                "www.bing.com",
                "cn.bing.com",
                "www.baidu.com",
                "duckduckgo.com",
                "www.duckduckgo.com",
                "www.python.org",
            }
            and ("q=" in url or "wd=" in url)
            for url in observed
        ), "No actual public search page was observed"
    if spec.get("handoff"):
        executors = instance.db(
            "SELECT id,intent_json,created_ms FROM tasks WHERE origin_conversation_id=? ORDER BY created_ms",
            (cid,),
        )
        kinds = [json.loads(row["intent_json"])["executor"] for row in executors]
        assert (
            "native" in kinds
            and "codex" in kinds
            and kinds.index("native") < kinds.index("codex")
        ), "No native research to Codex writing handoff"
        writer = next(
            row
            for row in executors
            if json.loads(row["intent_json"])["executor"] == "codex"
        )
        writer_goal = json.loads(writer["intent_json"])["goal"]
        transferred = sorted(url for url in verified if url in writer_goal)
        assert transferred, (
            "Codex task did not receive the actually retrieved source URLs"
        )
        result["handoffProof"] = {
            "researchTaskIds": [
                row["id"]
                for row in executors
                if row["created_ms"] < writer["created_ms"]
                and json.loads(row["intent_json"])["executor"] == "native"
            ],
            "writerTaskId": writer["id"],
            "transferredSourceUrls": transferred,
        }
    if spec.get("runExample"):
        demo = directory / "demo.py"
        assert demo.is_file(), "Runnable example was not created"
        example_calls = instance.db(
            "SELECT tc.*,m.content_json FROM tool_calls tc JOIN turns tr ON tr.id=tc.turn_id "
            "JOIN task_attempts a ON a.native_branch_id=tr.branch_id JOIN tasks t ON t.id=a.task_id "
            "JOIN messages m ON m.id=tc.result_message_id WHERE t.origin_conversation_id=? AND tc.tool_name IN ('shell','bash') AND tc.state='succeeded'",
            (cid,),
        )
        assert any(
            tool_result(item).get("exitCode") == 0
            and tool_result(item).get("stdout", "").strip() == "927"
            and "demo.py" in item["arguments_json"]
            for item in example_calls
        ), "Example was not actually run with the expected stdout and exit status"
    assert spec["name"] in answer and "/api/file/" in answer, (
        "Main did not deliver an openable document link"
    )
    delivered_urls = re.findall(
        r"(/api/file/(?:raw\?[^\s<\)\]]+|serve/[^\s<\)\]]+))", answer
    )
    valid_delivery = None
    for delivered_url in delivered_urls:
        if spec["name"] not in delivered_url:
            continue
        try:
            if (
                instance.request(delivered_url.replace("&amp;", "&"), read_bytes=True)
                == body
            ):
                valid_delivery = delivered_url
                break
        except OSError:
            continue
    assert valid_delivery, (
        "The document link actually returned by Main is broken or points to different contents"
    )
    if path.suffix == ".html":
        assert "<h1" in text.lower() and "<script" not in text.lower(), (
            "HTML lacks its report heading or has scripts"
        )
    professional = None
    if spec.get("handoff"):
        professional = validate_professional_readback(instance, cid, path, body)
        result["professionalReadbackProof"] = professional
    families = {
        "skill_read": "skill",
        "file_write": "write",
        "file_read": "read",
        "shell": "bash",
    }
    kinds = {families.get(call["tool_name"], call["tool_name"]) for call in successful}
    if professional:
        kinds.update(["professional.command", "professional.write"])
    assert len(kinds) >= 3, "No observable multi-tool workflow"
    loaded = {}
    for call in successful:
        if call["tool_name"] == "skill_read":
            name = json.loads(call["arguments_json"])["name"]
            content = tool_result(call)
            loaded[name] = {"version": content.get("version"), "at": call["created_ms"]}
    if professional:
        for skill in spec.get("skills", []):
            if skill in loaded:
                continue
            marker = instance.state["skillMarkers"][skill]
            skill_path = instance.root / "workflow-skills" / skill / "SKILL.md"
            assert marker in text and marker not in professional["delegatedGoal"], (
                "Professional writer did not independently obtain the opaque Skill receipt"
            )
            loaded[skill] = {
                "version": hashlib.sha256(skill_path.read_bytes()).hexdigest(),
                "method": "isolated_file_receipt_transfer",
                "sourcePath": str(skill_path),
            }
    for skill in spec.get("skills", []):
        assert skill in loaded and re.fullmatch(
            r"[a-f0-9]{64}", loaded[skill].get("version") or ""
        ), "No actual versioned Skill load: " + skill
        marker = instance.state["skillMarkers"][skill]
        assert marker in text, (
            "Loaded Skill output was not carried into the document: " + skill
        )
    digest = hashlib.sha256(body).hexdigest()
    writes = [
        call
        for call in successful
        if call["tool_name"] == "file_write"
        and json.loads(call["arguments_json"]).get("path", "").endswith(spec["name"])
    ]
    if not spec.get("handoff"):
        assert writes, "No successful document write call"
        assert all(
            info["at"] < writes[-1]["created_ms"]
            for name, info in loaded.items()
            if name in spec.get("skills", [])
        ), "Skill was only loaded after writing"
        readbacks = [
            call
            for call in successful
            if call["created_ms"] >= writes[-1]["created_ms"]
            and call["tool_name"] == "file_read"
            and tool_result(call).get("sha256") == digest
        ]
        assert readbacks, "Agent did not read back and verify the delivered document"
    if case.get("attachment"):
        source = instance.db(
            "SELECT content_json FROM messages WHERE conversation_id=? AND role='user' ORDER BY seq LIMIT 1",
            (cid,),
        )
        artifact_ids = {
            item["id"]
            for item in json.loads(source[0]["content_json"]).get("attachments", [])
        }
        manifests = instance.db(
            "SELECT p.parts_json FROM prompt_manifests p JOIN turns tr ON tr.id=p.turn_id "
            "JOIN task_attempts a ON a.native_branch_id=tr.branch_id JOIN tasks t ON t.id=a.task_id "
            "WHERE t.origin_conversation_id=?",
            (cid,),
        )
        evidence = [
            item
            for manifest in manifests
            for item in json.loads(manifest["parts_json"]).get("attachmentEvidence", [])
        ]
        assert artifact_ids and artifact_ids <= {
            item["artifactId"] for item in evidence
        }, "Original uploads did not reach Worker model context"
        result["attachmentTransferProof"] = evidence
    if spec.get("memoryRecall"):
        validate_memory_recall(instance, cid, spec["memoryRecall"], result)
    result["agentMechanismProof"] = {
        "toolKinds": sorted(kinds),
        "skillVersions": loaded,
        "orderedCalls": [
            {
                "tool": call["tool_name"],
                "state": call["state"],
                "startedMs": call["created_ms"],
                "endedMs": call["updated_ms"],
            }
            for call in calls
        ],
        "agentReadBackVerified": bool(professional) or not spec.get("handoff"),
    }
    result["documentProof"] = {
        "path": str(path),
        "fileUrl": valid_delivery,
        "sha256": hashlib.sha256(body).hexdigest(),
        "verifiedSources": sorted(verified),
        "observedUrls": sorted(url for url in observed if url.startswith("http")),
        "authenticatedDownloadMatches": True,
    }


def execution_calls(instance, cid):
    return instance.db(
        "SELECT tc.*,m.content_json FROM tool_calls tc JOIN turns tr ON tr.id=tc.turn_id "
        "LEFT JOIN messages m ON m.id=tc.result_message_id WHERE tr.conversation_id=? OR "
        "tr.branch_id IN (SELECT a.native_branch_id FROM task_attempts a JOIN tasks t ON t.id=a.task_id WHERE t.origin_conversation_id=?) ORDER BY tc.created_ms,tc.id",
        (cid, cid),
    )


def tool_result(call):
    if not call.get("content_json"):
        return {}
    try:
        return json.loads(json.loads(call["content_json"])["text"])
    except (ValueError, TypeError, KeyError):
        return {}


def validate_memory_write(instance, cid, marker, result):
    records = instance.db(
        "SELECT r.id,r.revision,s.message_id,s.source_sha256 FROM memory_records r "
        "JOIN memory_sources s ON s.memory_id=r.id JOIN messages m ON m.id=s.message_id "
        "WHERE r.owner_id='local' AND r.state='active' AND r.body LIKE ? AND m.conversation_id=? AND m.role='user'",
        ("%" + marker + "%", cid),
    )
    assert records, "No active memory with the original user message as source"
    events = instance.db(
        "SELECT id,payload_json FROM events WHERE conversation_id=? AND kind='memory.remembered'",
        (cid,),
    )
    assert any(
        json.loads(event["payload_json"]).get("memoryId")
        in {record["id"] for record in records}
        for event in events
    ), "No committed automatic-memory receipt"
    result["memoryWriteProof"] = records


def execution_trace(instance, cid):
    trace = []
    for call in execution_calls(instance, cid):
        output = tool_result(call)
        state = call["state"]
        if state == "succeeded" and output.get("exitCode", 0) != 0:
            state = "failed"
        trace.append(
            {
                "tool": call["tool_name"],
                "state": state,
                "startedMs": call["created_ms"],
                "endedMs": call["updated_ms"],
                **({"exitCode": output["exitCode"]} if "exitCode" in output else {}),
            }
        )
    return trace


def validate_link_navigation(instance, case, cid, result):
    target_path = "/" + instance.link_paths[case["id"]]
    observations = instance.db(
        "SELECT o.id,o.body_json FROM resource_observations o JOIN tasks t ON t.id=o.task_id WHERE t.origin_conversation_id=?",
        (cid,),
    )
    calls = execution_calls(instance, cid)
    proof = []
    for observation in observations:
        page = json.loads(observation["body_json"])
        links = [
            control["href"]
            for control in page.get("controls", [])
            if control.get("href") and urlparse(control["href"]).path == target_path
        ]
        for call in calls:
            if call["tool_name"] != "browser_act" or call["state"] != "succeeded":
                continue
            args = json.loads(call["arguments_json"])
            if (
                args.get("observationId") == observation["id"]
                and args.get("kind") == "goto"
                and args.get("url") in links
            ):
                proof.append(
                    {
                        "observationId": observation["id"],
                        "sourceUrl": page["url"],
                        "observedHref": args["url"],
                        "toolCallId": call["id"],
                    }
                )
    assert proof, (
        "No navigation using the opaque href and its actual source observation"
    )
    assert any(
        urlparse(json.loads(item["body_json"]).get("url", "")).path == target_path
        for item in observations
    ), "Linked page was not actually observed"
    result["navigationProof"] = proof


def validate_memory_recall(instance, cid, marker, result):
    records = instance.db(
        "SELECT id,revision FROM memory_records WHERE owner_id='local' AND state='active' AND body LIKE ?",
        ("%" + marker + "%",),
    )
    manifests = instance.db(
        "SELECT p.parts_json FROM prompt_manifests p JOIN turns tr ON tr.id=p.turn_id WHERE tr.conversation_id=?",
        (cid,),
    )
    evidence = [
        item
        for manifest in manifests
        for item in json.loads(manifest["parts_json"]).get("memoryEvidence", [])
    ]
    assert any(
        item["memoryId"] == record["id"] and item["revision"] == record["revision"]
        for item in evidence
        for record in records
    ), "Stored preference was not actually admitted into Main context"
    result["memoryRecallProof"] = evidence


def validate_professional_readback(instance, cid, path, body):
    attempts = instance.db(
        "SELECT t.id,t.intent_json,a.result_json FROM tasks t JOIN task_attempts a ON a.task_id=t.id WHERE t.origin_conversation_id=? AND json_extract(t.intent_json,'$.executor')='codex' ORDER BY t.created_ms DESC",
        (cid,),
    )
    for attempt in attempts:
        report = json.loads(attempt["result_json"] or "{}")
        log = report.get("stderr", "")
        workspace = (report.get("workspace") or {}).get("directory", "")
        if report.get("exitCode") != 0 or workspace != str(path.parent):
            continue
        blob = hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()[:7]
        assert ".." + blob in log, (
            "Professional published-file diff does not match the delivered bytes"
        )
        assert (
            str(path) in log
            and ".read_text(" in log
            and re.search(r"succeeded in \d+ms", log)
        ), "No actual successful professional read-back command in the execution log"
        return {
            "taskId": attempt["id"],
            "executor": "codex",
            "exitCode": 0,
            "source": "execution.stderr",
            "logSha256": hashlib.sha256(log.encode()).hexdigest(),
            "workspace": workspace,
            "publishedGitBlob": blob,
            "delegatedGoal": json.loads(attempt["intent_json"])["goal"],
        }
    raise AssertionError(
        "No successful professional execution bound to the requested workspace"
    )
