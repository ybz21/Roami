"""Main-owned collaboration plans over revision-bound managed tasks."""

import asyncio
import hashlib
import json
import sqlite3

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_repository import (
    changed,
    dependency_ready,
    enqueue,
    group,
    receipt,
    snapshot,
)
from roami_agent.storage.swarm_scopes import project_scope, require_scope
from roami_agent.storage.transcript_repository import owned

EXECUTORS = {"native", "codex", "claude", "opencode", "pi"}


class SwarmPlans:
    def __init__(self, database, tasks, conversations, wakeup, *, settings=None):
        self.db, self.tasks, self.conversations, self.wakeup = (
            database,
            tasks,
            conversations,
            wakeup,
        )
        self.settings = settings
        self.chat = None
        self.locks = {}

    def lock(self, swarm_id):
        return self.locks.setdefault(swarm_id, asyncio.Lock())

    async def create(self, owner, spec, *, binding=None):
        cid = spec.get("mainConversationId")
        target = spec.get("target") or {"kind": "new_session"}
        if not isinstance(target, dict) or target.get("kind") not in {"project", "new_session"}:
            raise DomainError("INVALID_TASK_TARGET")
        if target["kind"] == "project":
            if not isinstance(target.get("projectId"), str) or not target["projectId"].strip():
                raise DomainError("INVALID_TASK_TARGET")
            target = {key: value for key, value in target.items() if key != "directory"}
        name, goal = str(spec.get("name", "")).strip(), str(spec.get("goal", "")).strip()
        if not name or len(name) > 100 or not goal or len(goal) > 30000:
            raise DomainError("INVALID_SWARM")
        bound = binding is not None

        def origin(db):
            if not bound:
                return None
            if not isinstance(binding, dict):
                raise DomainError("TASK_REQUIRES_ORIGIN_MESSAGE", 409)
            source = row(
                db,
                "SELECT m.id,m.conversation_id FROM messages m JOIN turns t ON t.id=m.turn_id "
                "AND t.conversation_id=m.conversation_id JOIN conversations c ON c.id=m.conversation_id "
                "WHERE t.id=? AND t.trigger_kind='user' AND t.state IN ('queued','running') "
                "AND t.branch_id=c.active_branch_id AND m.role='user' AND c.owner_id=? "
                "AND c.deleted_ms IS NULL AND m.deleted_ms IS NULL AND m.status!='deleted' "
                "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=c.owner_id AND o.message_id=m.id) "
                "ORDER BY m.seq LIMIT 1",
                (binding.get("turnId"), owner),
            )
            if not source or any(
                value and value != source["conversation_id"]
                for value in (cid, binding.get("conversation"))
            ):
                raise DomainError("TASK_REQUIRES_ORIGIN_MESSAGE", 409)
            assert_context_admitted(
                db,
                {
                    "id": binding["turnId"],
                    "owner_id": owner,
                    "conversation_id": source["conversation_id"],
                },
            )
            return source

        if bound:
            source = await self.db.call(origin)
            cid = source["conversation_id"]
        if not cid:
            cid = (
                await self.conversations.create(owner, name, project_id=target["projectId"])
                if target["kind"] == "project"
                else await self.conversations.main(owner)
            )["id"]
        payload = {**spec, "mainConversationId": cid, "target": target}

        def write(db):
            source = origin(db)
            scope = project_scope(db, owner, cid, target)

            def new():
                conversation = owned(db, owner, cid)
                if row(
                    db,
                    "SELECT id FROM native_sessions WHERE conversation_id=? UNION ALL SELECT id FROM swarm_member_instances WHERE conversation_id=?",
                    (cid, cid),
                ):
                    raise DomainError("SWARM_MAIN_REQUIRED", 409)
                project = row(
                    db,
                    "SELECT project_id FROM project_okr_conversations WHERE conversation_id=? AND owner_id=?",
                    (cid, owner),
                )
                if project and (
                    target.get("kind") != "project"
                    or target.get("projectId") != project["project_id"]
                ):
                    raise DomainError("PROJECT_OKR_TEAM_CONFLICT", 409)
                sid = "sw-" + identity()
                db.execute(
                    "INSERT INTO swarm_groups(id,owner_id,name,conversation_id,goal,target_json,created_ms,updated_ms,scope_project_id,origin_message_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        sid,
                        owner,
                        name,
                        cid,
                        goal,
                        encoded(target),
                        now_ms(),
                        now_ms(),
                        scope,
                        source["id"] if source else None,
                    ),
                )
                value = group(db, owner, sid)
                changed(db, value, "swarm.created")
                return {"id": sid, "mainConversationId": conversation["id"], "revision": 1}

            result = receipt(db, owner, spec["commandKey"], payload, new, scope_project_id=scope)
            if source:
                db.execute(
                    "UPDATE swarm_groups SET origin_message_id=COALESCE(origin_message_id,?) WHERE id=?",
                    (source["id"], result["id"]),
                )
            return result

        try:
            result = await self.db.call(write, write=True)
        except sqlite3.IntegrityError as exc:
            raise DomainError("SWARM_NAME_EXISTS", 409) from exc
        if not bound and self.chat:
            kickoff = (
                goal
                + "\n\nSwarm collaboration ID: "
                + result["id"]
                + ". You are the existing Roami Main coordinating this swarm. Discover swarm_members_register, swarm_plan and swarm_status using tool_list. Register genuine long-lived roles first, then assign work with their stable memberId. Plan named members with appropriate executors, goals and acceptance criteria; create a final integration item with verified dependencies. Use swarm_post for shared discussion and swarm_memory_read/write for durable team knowledge. Declare artifact or external_action deliverables when the requested outcome needs files or real external actions; plans and URLs are not completion. For later rounds reuse the existing named member and task via task_steer; never append r2/r3 members to replace its conversation. task_steer forwards the current user request and records it in the group/member thread. swarm_post only writes discussion; it does not deliver work. Use session_send only for a verified unrelated legacy session with its durable reply channel. Do not start a separate commander or use legacy swarm add. Report blockers and verified deliverables here."
                + " Use the exact registered CLI command and input schema returned by tool_list or roami swarm help. Submit each managed command alone: no cd prefix, shell chaining or pipes; the host binds the execution context. Never probe a write operation with placeholder goals or acceptance criteria. Planning dispatches real tasks, so every item must carry its complete actual instructions and acceptance before submission."
            )
            start = await self.conversations.accept(
                owner, cid, "swarm.start:" + result["id"], kickoff
            )

            def bind_origin(db):
                db.execute(
                    "UPDATE swarm_groups SET origin_message_id=COALESCE(origin_message_id,?) WHERE id=?",
                    (start["messageId"], result["id"]),
                )
                if not row(
                    db,
                    "SELECT id FROM swarm_posts WHERE swarm_id=? AND turn_id=?",
                    (result["id"], start["turnId"]),
                ):
                    db.execute(
                        "INSERT INTO swarm_posts(swarm_id,author,text,created_ms,turn_id) VALUES(?,'human',?,?,?)",
                        (result["id"], goal, now_ms(), start["turnId"]),
                    )
                enqueue(db, result["id"], identity())

            await self.db.call(bind_origin, write=True)
            self.wakeup.set()
        return result

    async def list(self, owner):
        ids = await self.db.call(
            lambda db: rows(
                db,
                "SELECT g.id FROM swarm_groups g JOIN conversations c ON c.id=g.conversation_id WHERE g.owner_id=? AND c.deleted_ms IS NULL ORDER BY g.updated_ms DESC",
                (owner,),
            )
        )
        return [await self.snapshot(owner, item["id"], include_memory=False) for item in ids]

    async def snapshot(self, owner, sid, *, include_memory=True):
        value = await self.db.call(lambda db: snapshot(db, owner, sid))
        if include_memory:
            value["teamMemory"] = await self.memory_read(owner, sid)
        return value

    async def register_members(self, owner, sid, spec):
        items = spec.get("members")
        if not isinstance(items, list) or not items or len(items) > 100:
            raise DomainError("INVALID_SWARM_MEMBERS")

        def write(db):
            def apply():
                value = group(db, owner, sid)
                self.mutable(value, spec)
                from roami_agent.storage.swarm_members import member_for_plan

                result = []
                for item in items:
                    if not isinstance(item, dict):
                        raise DomainError("INVALID_SWARM_MEMBER")
                    member = member_for_plan(
                        db, value, item.get("name"), item.get("executor"), item.get("duty")
                    )
                    if member["duty"] != item["duty"].strip():
                        raise DomainError("SWARM_MEMBER_DUTY_CONFLICT", 409)
                    result.append(member)
                db.execute(
                    "UPDATE swarm_groups SET revision=revision+1,member_protocol=1 WHERE id=?",
                    (sid,),
                )
                value["revision"] += 1
                changed(db, value, "swarm.members_changed")
                return {"id": sid, "revision": value["revision"], "members": result}

            return receipt(
                db, owner, spec["commandKey"], {"swarmId": sid, **spec}, apply, swarm_id=sid
            )

        async with self.lock(sid):
            return await self.db.call(write, write=True)

    async def member(self, owner, sid, member_id, *, before=None, limit=20):
        if (
            type(limit) is not int
            or not 1 <= limit <= 50
            or before is not None
            and (type(before) is not int or before < 1)
        ):
            raise DomainError("INVALID_SWARM_MEMBER_PAGE")

        def read(db):
            info = snapshot(db, owner, sid)
            member = next((item for item in info["members"] if item["id"] == member_id), None)
            if not member:
                raise DomainError("SWARM_MEMBER_NOT_FOUND", 404)
            member["duty"] = row(db, "SELECT duty FROM swarm_members WHERE id=?", (member_id,))[
                "duty"
            ]
            from roami_agent.storage.swarm_members import round_page

            return {"member": member, "rounds": round_page(db, owner, member_id, before, limit)}

        return await self.db.call(read)

    async def memory_read(self, owner, sid):
        from roami_agent.storage.swarm_memory import read_memory

        return await read_memory(self, owner, sid)

    async def memory_write(self, owner, sid, spec):
        from roami_agent.storage.swarm_memory import write_memory

        async with self.lock(sid):
            return await write_memory(self, owner, sid, spec)

    async def context(self, turn):
        groups = await self.db.call(
            lambda db: rows(
                db,
                "SELECT DISTINCT g.id FROM swarm_groups g LEFT JOIN swarm_work_items w ON w.swarm_id=g.id "
                "WHERE g.owner_id=? AND g.archived=0 AND (g.conversation_id=? OR w.task_id=?) "
                "ORDER BY g.updated_ms DESC LIMIT 5",
                (
                    turn["owner_id"],
                    turn["conversation_id"],
                    turn.get("taskId")
                    or (
                        row(
                            db,
                            "SELECT task_id FROM task_attempts WHERE id=?",
                            (turn.get("executionRunId"),),
                        )
                        or {}
                    ).get("task_id"),
                ),
            )
        )
        values = []
        for value in groups:
            memory = await self.memory_read(turn["owner_id"], value["id"])
            if isinstance(memory.get("content"), str) and len(memory["content"]) > 8000:
                memory = {**memory, "content": memory["content"][:8000], "truncated": True}
            values.append({"swarmId": value["id"], "teamMemory": memory})
        return values

    async def plan(self, owner, sid, spec):
        items = spec.get("items", [])
        if not isinstance(items, list) or not items or len(items) > 100:
            raise DomainError("INVALID_SWARM_PLAN")

        def write(db):
            def apply():
                value = group(db, owner, sid)
                self.mutable(value, spec)
                existing = rows(db, "SELECT * FROM swarm_work_items WHERE swarm_id=?", (sid,))
                by_name = {item["member_name"]: item["id"] for item in existing}
                for item in items:
                    if (
                        not isinstance(item, dict)
                        or not isinstance(item.get("dependencies", []), list)
                        or any(not isinstance(dep, dict) for dep in item.get("dependencies", []))
                    ):
                        raise DomainError("INVALID_SWARM_PLAN")
                    if (
                        not all(
                            isinstance(item.get(key), str) and item[key].strip()
                            for key in ("member", "title", "goal", "acceptance")
                        )
                        or item.get("executor") not in EXECUTORS
                    ):
                        raise DomainError("INVALID_SWARM_PLAN")
                    from roami_agent.storage.swarm_evidence import validate_deliverables

                    validate_deliverables(item.get("deliverables", []))
                    name = item["member"].strip()
                    if (
                        name.casefold() in {"leader", "main"}
                        or name in by_name
                        or len(name) > 80
                        or len(item["title"]) > 80
                        or len(item["goal"]) > 30000
                        or len(item["acceptance"]) > 8000
                    ):
                        raise DomainError("INVALID_SWARM_MEMBER")
                    from roami_agent.storage.swarm_members import member_for_plan

                    if value["member_protocol"] and not item.get("memberId"):
                        raise DomainError("SWARM_MEMBER_ID_REQUIRED", 409)
                    member = member_for_plan(
                        db, value, name, item["executor"], item["title"], item.get("memberId")
                    )
                    if row(
                        db,
                        "SELECT work_id FROM swarm_member_work WHERE member_id=?",
                        (member["id"],),
                    ):
                        raise DomainError("INVALID_SWARM_MEMBER")
                    ident = identity()
                    by_name[name] = ident
                    db.execute(
                        "INSERT INTO swarm_work_items(id,swarm_id,member_name,executor,title,goal,acceptance,integration,deliverables_json) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            ident,
                            sid,
                            name,
                            item["executor"],
                            item["title"],
                            item["goal"],
                            item["acceptance"],
                            int(item.get("integration") is True),
                            encoded(item.get("deliverables", [])),
                        ),
                    )
                    db.execute("INSERT INTO swarm_member_work VALUES(?,?)", (member["id"], ident))
                    db.execute(
                        "UPDATE swarm_members SET current_work_id=? WHERE id=?",
                        (ident, member["id"]),
                    )
                for item in items:
                    dependencies = list(item.get("dependencies", []))
                    if item.get("integration") is True:
                        known = {dep.get("member") for dep in dependencies}
                        dependencies.extend(
                            {
                                "member": name,
                                "revision": (
                                    row(
                                        db,
                                        "SELECT t.revision FROM tasks t JOIN swarm_work_items w ON w.task_id=t.id WHERE w.id=?",
                                        (by_name[name],),
                                    )
                                    or {}
                                ).get("revision", 1),
                            }
                            for name in by_name
                            if name != item["member"].strip() and name not in known
                        )
                    for dep in dependencies:
                        if not isinstance(dep.get("member"), str) or (
                            dep.get("artifactId") is not None
                            and not isinstance(dep["artifactId"], str)
                        ):
                            raise DomainError("INVALID_SWARM_DEPENDENCY")
                        upstream = by_name.get(dep.get("member"))
                        revision = dep.get("revision", 1)
                        if not upstream or type(revision) is not int or revision < 1:
                            raise DomainError("INVALID_SWARM_DEPENDENCY")
                        db.execute(
                            "INSERT INTO swarm_dependencies VALUES(?,?,?,?)",
                            (
                                by_name[item["member"].strip()],
                                upstream,
                                revision,
                                dep.get("artifactId"),
                            ),
                        )
                edges = rows(
                    db,
                    "SELECT d.work_id,d.upstream_id FROM swarm_dependencies d JOIN swarm_work_items w ON w.id=d.work_id WHERE w.swarm_id=?",
                    (sid,),
                )
                graph = {ident: [] for ident in by_name.values()}
                for edge in edges:
                    graph[edge["work_id"]].append(edge["upstream_id"])
                visiting, visited = set(), set()

                def visit(ident):
                    if ident in visiting:
                        raise DomainError("SWARM_DEPENDENCY_CYCLE", 409)
                    if ident in visited:
                        return
                    visiting.add(ident)
                    for upstream in graph[ident]:
                        visit(upstream)
                    visiting.remove(ident)
                    visited.add(ident)

                for ident in graph:
                    visit(ident)
                value["revision"] += 1
                db.execute(
                    "UPDATE swarm_groups SET revision=? WHERE id=?", (value["revision"], sid)
                )
                changed(db, value, "swarm.plan_changed")
                enqueue(db, sid, identity())
                return {"id": sid, "revision": value["revision"]}

            return receipt(
                db, owner, spec["commandKey"], {"swarmId": sid, **spec}, apply, swarm_id=sid
            )

        async with self.lock(sid):
            try:
                result = await self.db.call(write, write=True)
            except sqlite3.IntegrityError as exc:
                raise DomainError("INVALID_SWARM_DEPENDENCY", 409) from exc
        self.wakeup.set()
        return result

    @staticmethod
    def mutable(value, spec):
        if value["archived"]:
            raise DomainError("SWARM_ARCHIVED", 409)
        if spec.get("expectedRevision") != value["revision"]:
            raise DomainError("SWARM_PLAN_CHANGED", 409)

    async def control(self, owner, sid, spec):
        action = spec.get("action")
        if action not in {"pause", "resume", "archive", "stop"}:
            raise DomainError("INVALID_SWARM_ACTION")

        def write(db):
            def apply():
                value = group(db, owner, sid)
                self.mutable(value, spec)
                db.execute(
                    "UPDATE swarm_groups SET paused=?,archived=?,revision=revision+1 WHERE id=?",
                    (int(action != "resume"), int(action == "archive"), sid),
                )
                value["revision"] += 1
                changed(db, value)
                if action == "resume":
                    enqueue(db, sid, identity())
                targets = (
                    rows(
                        db,
                        "SELECT t.id AS taskId,t.revision FROM tasks t JOIN swarm_work_items w ON w.task_id=t.id WHERE w.swarm_id=?",
                        (sid,),
                    )
                    if action == "stop"
                    else []
                )
                return {
                    "id": sid,
                    "revision": value["revision"],
                    "action": action,
                    "targets": targets,
                }

            return receipt(
                db, owner, spec["commandKey"], {"swarmId": sid, **spec}, apply, swarm_id=sid
            )

        async with self.lock(sid):
            result = await self.db.call(write, write=True)
            if action == "stop":
                for item in result["targets"]:
                    try:
                        await self.tasks.cancel(
                            owner, item["taskId"], expected_revision=item["revision"]
                        )
                    except DomainError as exc:
                        if exc.code != "TASK_REVISION_CHANGED":
                            raise
        self.wakeup.set()
        return result

    async def post(self, owner, sid, spec, *, binding=None):
        if binding is not None and (not isinstance(binding, dict) or not binding):
            raise DomainError("SWARM_MAIN_REQUIRED", 403)
        text = spec.get("text", "").strip()
        if not text or len(text) > 8000:
            raise DomainError("INVALID_SWARM_MESSAGE")
        identity_binding = (
            {
                key: binding[key]
                for key in ("conversation", "taskId", "runId", "taskRevision")
                if key in binding
            }
            if binding
            else None
        )

        def write(db):
            def apply():
                from roami_agent.dispatch.swarm_message_binding import bound_member
                from roami_agent.storage.swarm_inbox import record_post

                value = group(db, owner, sid)
                if value["archived"]:
                    raise DomainError("SWARM_ARCHIVED", 409)
                actor = bound_member(db, value, binding) if binding is not None else None
                author = "human"
                task_id = None
                if spec.get("workId"):
                    target = row(
                        db,
                        "SELECT task_id FROM swarm_work_items WHERE swarm_id=? AND id=?",
                        (sid, spec["workId"]),
                    )
                    if not target or not target["task_id"]:
                        raise DomainError("SWARM_MEMBER_TASK_REQUIRED", 409)
                    task_id = target["task_id"]
                    revision = spec.get("taskRevision")
                    if type(revision) is not int or revision < 1:
                        raise DomainError("TASK_REVISION_REQUIRED", 409)
                    current = row(db, "SELECT revision FROM tasks WHERE id=?", (task_id,))
                    if not current or current["revision"] != revision:
                        raise DomainError("TASK_REVISION_CHANGED", 409)
                if binding is not None:
                    if binding.get("taskId"):
                        if spec.get("workId"):
                            raise DomainError("SWARM_MAIN_REQUIRED", 403)
                        task_id = binding["taskId"]
                        author = actor["name"]
                    else:
                        author = "main"
                delivery_key = (
                    "swarm.message:"
                    + hashlib.sha256(encoded([sid, spec["commandKey"]]).encode()).hexdigest()
                )
                result, created = record_post(
                    db, value, spec, author, task_id, binding, delivery_key
                )
                if created:
                    changed(db, value, "swarm.message")
                return result

            return receipt(
                db,
                owner,
                spec["commandKey"],
                {"swarmId": sid, **spec, "binding": identity_binding},
                apply,
                swarm_id=sid,
            )

        return await self.db.call(write, write=True)

    async def inbox(self, owner, sid, spec, *, binding=None):
        from roami_agent.dispatch.swarm_message_binding import bound_member
        from roami_agent.storage.swarm_inbox import inbox

        def read(db):
            value = group(db, owner, sid)
            member_id = spec.get("memberId")
            if binding is not None:
                actor = bound_member(db, value, binding)
                member_id = actor["id"] if actor else None
                if spec.get("memberId") not in (None, member_id):
                    raise DomainError("SWARM_MEMBER_REQUIRED", 403)
            before_changes = db.total_changes
            result = inbox(
                db,
                value,
                member_id=member_id,
                limit=spec.get("limit", 20),
                before=spec.get("before"),
                mark_read=binding is not None,
            )
            if db.total_changes > before_changes:
                changed(db, value, "swarm.inbox.read")
            return result

        return await self.db.call(read, write=binding is not None)

    async def advance(self, job):
        sid = job["aggregate_id"]
        async with self.lock(sid):

            def admitted(db):
                value = row(db, "SELECT * FROM swarm_groups WHERE id=?", (sid,))
                if value:
                    try:
                        require_scope(group(db, value["owner_id"], sid))
                    except DomainError as exc:
                        pending = db.execute(
                            "UPDATE swarm_work_items SET dispatch_error=? WHERE swarm_id=? AND task_id IS NULL AND dispatch_error IS NULL",
                            (exc.code, sid),
                        )
                        if pending.rowcount:
                            changed(db, value)
                        return None
                return value

            info = await self.db.call(admitted, write=True)
            if info and info["origin_message_id"] and not info["paused"] and not info["archived"]:
                stale_tasks = await self.db.call(
                    lambda db: rows(
                        db,
                        "SELECT DISTINCT downstream.task_id,active.revision FROM swarm_work_items downstream JOIN tasks active ON active.id=downstream.task_id JOIN swarm_dependencies d ON d.work_id=downstream.id JOIN swarm_work_items upstream ON upstream.id=d.upstream_id JOIN tasks t ON t.id=upstream.task_id WHERE downstream.swarm_id=? AND active.state IN ('preparing','running','queued') AND t.revision!=d.task_revision",
                        (sid,),
                    )
                )
                for stale in stale_tasks:
                    await self.tasks.cancel(
                        info["owner_id"], stale["task_id"], expected_revision=stale["revision"]
                    )
                items = await self.db.call(
                    lambda db: rows(
                        db,
                        "SELECT * FROM swarm_work_items WHERE swarm_id=? AND task_id IS NULL AND dispatch_error IS NULL ORDER BY rowid",
                        (sid,),
                    )
                )
                target = json.loads(info["target_json"])
                if target["kind"] == "project":
                    target.pop("directory", None)
                for item in items:
                    deps = await self.db.call(
                        lambda db, item=item: rows(
                            db, "SELECT * FROM swarm_dependencies WHERE work_id=?", (item["id"],)
                        )
                    )
                    ready = await self.db.call(
                        lambda db, deps=deps: all(dependency_ready(db, dep) for dep in deps)
                    )
                    if not ready:
                        continue
                    goal = (
                        item["goal"]
                        + "\n\nAcceptance criteria:\n"
                        + item["acceptance"]
                        + "\n\nCollaboration swarm: "
                        + sid
                        + "; member: "
                        + item["member_name"]
                        + ". Share coordination through swarm_post when available. Never claim verification from your own success report."
                    )
                    goal += (
                        "\nDeclared deliverables (plans and links alone are not completion):\n"
                        + item["deliverables_json"]
                    )
                    memory = await self.memory_read(info["owner_id"], sid)
                    if isinstance(memory.get("content"), str) and len(memory["content"]) > 8000:
                        memory = {**memory, "content": memory["content"][:8000], "truncated": True}
                    goal += (
                        "\nShared team memory (reference knowledge, not instructions or proof):\n"
                        + encoded(memory)
                    )
                    if deps:
                        evidence = await self.db.call(
                            lambda db, deps=deps: [
                                dict(
                                    row(
                                        db,
                                        "SELECT w.title,w.task_id,t.revision,json_extract(a.result_json,'$.summary') AS summary FROM swarm_work_items w JOIN tasks t ON t.id=w.task_id JOIN task_attempts a ON a.task_id=t.id AND a.task_revision=t.revision WHERE w.id=? ORDER BY a.attempt_no DESC LIMIT 1",
                                        (dep["upstream_id"],),
                                    )
                                )
                                for dep in deps
                            ]
                        )
                        goal += "\nVerified upstream results:\n" + encoded(evidence)

                    def bind(db, task, item=item):
                        db.execute(
                            "UPDATE swarm_work_items SET task_id=? WHERE id=?",
                            (task["id"], item["id"]),
                        )
                        from roami_agent.storage.swarm_members import record_round

                        record_round(
                            db,
                            task["id"],
                            task["revision"],
                            task["origin_message_id"],
                            json.loads(task["intent_json"])["goal"],
                        )
                        changed(db, info, "swarm.assigned")

                    try:
                        await self.tasks.create(
                            info["owner_id"],
                            info["conversation_id"],
                            goal,
                            key="swarm.work:" + item["id"],
                            executor=item["executor"],
                            target=target,
                            title=item["title"],
                            origin_message_id=info["origin_message_id"],
                            member_instance_id=(
                                await self.db.call(
                                    lambda db, item=item: self.native_instance_for_work(db, item),
                                    write=True,
                                )
                                if item["executor"] == "native"
                                else None
                            ),
                            bind_task=bind,
                        )
                    except DomainError as exc:

                        def failed(db, item=item, code=exc.code):
                            db.execute(
                                "UPDATE swarm_work_items SET dispatch_error=? WHERE id=?",
                                (code, item["id"]),
                            )
                            changed(db, info)

                        await self.db.call(failed, write=True)
                        continue

        await self.db.call(
            lambda db: db.execute("UPDATE jobs SET state='done' WHERE id=?", (job["id"],)),
            write=True,
        )
        self.wakeup.set()

    @staticmethod
    def native_instance_for_work(db, item):
        from roami_agent.storage.member_instances import ensure_native_instance

        member = row(
            db,
            "SELECT m.* FROM swarm_members m JOIN swarm_member_work b ON b.member_id=m.id WHERE b.work_id=?",
            (item["id"],),
        )
        if not member:
            raise DomainError("MEMBER_INSTANCE_BINDING_CONFLICT", 409)
        instance = ensure_native_instance(db, member)
        return instance["id"] if instance else None

    async def dependencies(self, owner, sid, spec):
        def write(db):
            def apply():
                value = group(db, owner, sid)
                self.mutable(value, spec)
                work = row(
                    db,
                    "SELECT * FROM swarm_work_items WHERE id=? AND swarm_id=?",
                    (spec["workId"], sid),
                )
                if not work:
                    raise DomainError("SWARM_MEMBER_TASK_REQUIRED", 404)
                if work["task_id"]:
                    task = row(
                        db, "SELECT state,revision FROM tasks WHERE id=?", (work["task_id"],)
                    )
                    attempt = row(
                        db,
                        "SELECT state,result_json FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
                        (work["task_id"],),
                    )
                    result = json.loads(attempt["result_json"] or "{}")
                    if (
                        task["state"] in {"preparing", "running", "cancelling"}
                        or attempt["state"] == "unknown"
                        or result.get("outcomeKnown") is False
                        or result.get("inputStopped") is False
                    ):
                        raise DomainError("SWARM_STOP_REQUIRED", 409)
                previous = rows(
                    db, "SELECT * FROM swarm_dependencies WHERE work_id=?", (work["id"],)
                )
                db.execute("DELETE FROM swarm_dependencies WHERE work_id=?", (work["id"],))
                for dep in spec.get("dependencies", []):
                    upstream = row(
                        db,
                        "SELECT id FROM swarm_work_items WHERE swarm_id=? AND member_name=?",
                        (sid, dep["member"]),
                    )
                    if not upstream or upstream["id"] == work["id"]:
                        raise DomainError("INVALID_SWARM_DEPENDENCY")
                    db.execute(
                        "INSERT INTO swarm_dependencies VALUES(?,?,?,?)",
                        (work["id"], upstream["id"], dep.get("revision", 1), dep.get("artifactId")),
                    )
                cycle = db.execute(
                    "WITH RECURSIVE walk(id) AS (SELECT upstream_id FROM swarm_dependencies WHERE work_id=? UNION SELECT d.upstream_id FROM swarm_dependencies d JOIN walk w ON d.work_id=w.id) SELECT 1 FROM walk WHERE id=?",
                    (work["id"], work["id"]),
                ).fetchone()
                if cycle:
                    raise DomainError("SWARM_DEPENDENCY_CYCLE", 409)
                current = rows(
                    db, "SELECT * FROM swarm_dependencies WHERE work_id=?", (work["id"],)
                )
                if work["task_id"] and {tuple(dep.values()) for dep in previous} != {
                    tuple(dep.values()) for dep in current
                }:
                    # Rebinding changes inputs, not the meaning of an already accepted run.
                    db.execute(
                        "UPDATE swarm_work_items SET required_task_revision=MAX(required_task_revision,?) WHERE id=?",
                        (task["revision"] + 1, work["id"]),
                    )
                db.execute(
                    "UPDATE swarm_work_items SET dispatch_error=NULL WHERE id=?", (work["id"],)
                )
                db.execute("UPDATE swarm_groups SET revision=revision+1 WHERE id=?", (sid,))
                value["revision"] += 1
                changed(db, value, "swarm.dependencies_changed")
                enqueue(db, sid, identity())
                return {"id": sid, "revision": value["revision"], "taskId": work["task_id"]}

            return receipt(
                db, owner, spec["commandKey"], {"swarmId": sid, **spec}, apply, swarm_id=sid
            )

        async with self.lock(sid):
            result = await self.db.call(write, write=True)
        self.wakeup.set()
        return result

    async def recover(self):
        def write(db):
            db.execute(
                "UPDATE jobs SET state='queued' WHERE kind='swarm.advance' AND state='running'"
            )
            for item in rows(db, "SELECT id FROM swarm_groups WHERE paused=0 AND archived=0"):
                enqueue(db, item["id"], identity())

        await self.db.call(write, write=True)

    async def send(self, owner, sid, spec):
        from roami_agent.storage.swarm_mentions import recipient

        info = await self.db.call(lambda db: snapshot(db, owner, sid))
        spec = recipient(spec, info)
        posted = await self.post(owner, sid, spec)
        post_id = posted["id"]
        stored = await self.db.call(
            lambda db: row(
                db, "SELECT delivery_json,delivery_key FROM swarm_posts WHERE id=?", (post_id,)
            )
        )
        if stored["delivery_json"]:
            return json.loads(stored["delivery_json"])
        key = stored["delivery_key"] or "swarm.message:" + spec["commandKey"]
        if spec.get("workId"):
            item = next((item for item in info["work"] if item["id"] == spec["workId"]), None)
            if not item or not item["task_id"]:
                raise DomainError("SWARM_MEMBER_TASK_REQUIRED", 409)
            result = await self.tasks.revisions.request(
                owner, item["task_id"], spec["text"], spec.get("taskRevision"), key
            )
        elif self.chat:
            result = await self.chat.submit(owner, info["mainConversationId"], key, spec["text"])
        else:
            raise DomainError("AGENT_RUNTIME_UNAVAILABLE", 503)

        def delivered(db):
            db.execute(
                "UPDATE swarm_posts SET delivery_json=?,turn_id=? WHERE id=?",
                (encoded(result), result.get("turnId"), post_id),
            )
            changed(db, group(db, owner, sid), "swarm.message_delivered")

        await self.db.call(delivered, write=True)
        self.wakeup.set()
        return result
