"""Main cannot inject legacy work into a managed member, including after completion."""

import json

import pytest
from test_runtime import ConversationModel
from test_session_dispatches import origin

from roami_agent.app import Runtime
from roami_agent.executors import targets
from roami_agent.executors.targets import TargetDirectory
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row


@pytest.fixture
async def routing(store):
    runtime = Runtime(store, ConversationModel())
    binding = await origin(runtime)
    yield runtime, binding, TargetDirectory(runtime.settings, runtime.session_dispatches)
    await runtime.close()


async def managed(runtime, *, owner="alice", state="succeeded", binding="attempt"):
    conversation = await runtime.conversations.create(owner, title="Private managed project")
    await runtime.conversations.accept(owner, conversation["id"], "managed", "Private project goal")
    task = await runtime.tasks.create(
        owner,
        conversation["id"],
        "Private managed instructions",
        key="managed",
        executor="codex",
        target={"kind": "session", "sessionId": "original-member"}
        if binding == "intent"
        else {"kind": "new_session"},
    )

    def bind(db):
        if binding == "attempt":
            db.execute(
                "UPDATE task_attempts SET state=?,session_id='original-member' WHERE task_id=?",
                (state, task["id"]),
            )
        elif binding == "target":
            db.execute(
                "UPDATE tasks SET target_json=? WHERE id=?",
                (json.dumps({"sessionId": "original-member"}), task["id"]),
            )

    await runtime.db.call(bind, write=True)
    return task


@pytest.mark.parametrize("alias", ["X维护", "$505", "original-member"])
@pytest.mark.parametrize("owner", ["alice", "bob"])
@pytest.mark.parametrize("state", ["running", "succeeded", "cancelled"])
async def test_all_managed_bindings_reject_before_dispatch_or_input(
    routing, store, monkeypatch, alias, owner, state
):
    runtime, binding, directory = routing
    task = await managed(runtime, owner=owner, state=state)
    queries = []

    async def execute(argv, **kwargs):
        queries.append(argv)
        assert argv[1:] == ["session", "resolve", alias, "--strict", "--json"]
        return {"exitCode": 0, "stdout": json.dumps({"id": "original-member", "label": "X"})}

    monkeypatch.setattr(targets, "execute", execute)
    with pytest.raises(DomainError, match="^TASK_SESSION_BINDING_REQUIRED$") as rejection:
        await directory.send(alias, "Continue work", "blocked", binding=binding)
    assert task["id"] not in str(rejection.value) and len(queries) == 1
    assert not await store.call(lambda db: row(db, "SELECT id FROM session_dispatches"))


@pytest.mark.parametrize("source", ["attempt", "target", "intent", "forget"])
async def test_admission_is_rechecked_after_awaited_strict_resolution(
    routing, store, monkeypatch, source
):
    runtime, binding, directory = routing

    async def resolve(kind, identifier):
        assert (kind, identifier) == ("session", "X")
        if source == "forget":
            await store.call(
                lambda db: db.execute(
                    "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'test',1)",
                    (binding["originMessageId"],),
                ),
                write=True,
            )
        else:
            await managed(runtime, binding=source)
        return {"sessionId": "original-member"}

    monkeypatch.setattr(directory, "resolve", resolve)
    code = "CONTEXT_SOURCE_FORGOTTEN" if source == "forget" else "TASK_SESSION_BINDING_REQUIRED"
    with pytest.raises(DomainError, match=code):
        await directory.send("X", "Continue work", "race", binding=binding)
    assert not await store.call(lambda db: row(db, "SELECT id FROM session_dispatches"))


async def test_prepared_dispatch_rechecks_binding_before_send(routing, store, monkeypatch):
    runtime, binding, directory = routing

    async def resolve(kind, identifier):
        return {"sessionId": "original-member"}

    monkeypatch.setattr(directory, "resolve", resolve)
    dispatch = await runtime.session_dispatches.prepare(
        "X", "Continue work", "prepared", binding, resolve=resolve
    )
    await managed(runtime)
    with pytest.raises(DomainError, match="TASK_SESSION_BINDING_REQUIRED"):
        await directory.send("X", "Continue work", "prepared", binding=binding)
    item = await store.call(
        lambda db: row(db, "SELECT * FROM session_dispatches WHERE id=?", (dispatch["id"],))
    )
    assert item["delivery_state"] == "prepared" and not item["delivery_receipt_json"]


@pytest.mark.parametrize("outcome", ["delivered", "unknown"])
async def test_historical_receipt_survives_binding_and_closed_target(
    routing, store, monkeypatch, outcome
):
    runtime, binding, directory = routing
    effects = []

    async def execute(argv, **kwargs):
        if argv[1:3] == ["session", "resolve"]:
            return {"exitCode": 0, "stdout": json.dumps({"id": "original-member", "label": "X"})}
        data = json.loads(kwargs["input_data"])
        assert data["sessionId"] == "original-member"
        effects.append(data)
        if outcome == "unknown":
            raise TimeoutError
        return {
            "exitCode": 0,
            "stdout": json.dumps(
                {"session": "original-member", "state": "delivered", "outcomeKnown": True}
            ),
        }

    monkeypatch.setattr(targets, "execute", execute)
    if outcome == "unknown":
        with pytest.raises(DomainError, match="TOOL_OUTCOME_UNKNOWN"):
            await directory.send("X", "Original work", "historical", binding=binding)
    else:
        receipt = await directory.send("X", "Original work", "historical", binding=binding)
    await managed(runtime)

    async def forbidden(*args, **kwargs):
        pytest.fail("Historical receipt must not resolve or submit again")

    monkeypatch.setattr(targets, "execute", forbidden)
    for _ in range(2):
        if outcome == "unknown":
            with pytest.raises(DomainError, match="TOOL_OUTCOME_UNKNOWN"):
                await directory.send("X", "Original work", "historical", binding=binding)
        else:
            assert (
                await directory.send("X", "Original work", "historical", binding=binding) == receipt
            )
    assert len(effects) == 1


async def test_go_binding_race_is_a_known_rejection_not_an_unknown_delivery(
    routing, store, monkeypatch
):
    runtime, binding, directory = routing
    sends = []

    async def execute(argv, **kwargs):
        if argv[1:3] == ["session", "resolve"]:
            return {"exitCode": 0, "stdout": json.dumps({"id": "original-member", "label": "X"})}
        sends.append(argv)
        return {"exitCode": 1, "stderr": "TASK_SESSION_BINDING_REQUIRED"}

    monkeypatch.setattr(targets, "execute", execute)
    for _ in range(2):
        with pytest.raises(DomainError, match="TASK_SESSION_BINDING_REQUIRED"):
            await directory.send("X", "Continue work", "race", binding=binding)
    dispatch = await store.call(lambda db: row(db, "SELECT * FROM session_dispatches"))
    assert len(sends) == 1 and dispatch["delivery_state"] == "failed"
    with pytest.raises(DomainError, match="SESSION_DISPATCH_NOT_DELIVERED"):
        await runtime.session_dispatches.report(
            "alice", dispatch["id"], {"key": "final", "status": "completed", "summary": "Not sent"}
        )
