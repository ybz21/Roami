"""Stop team work through cancellation; resume original tasks through trusted steering."""

import json

from roami_agent.dispatch.task_cancellation import request_task_cancellation
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.swarm_repository import changed, enqueue, group, receipt
from roami_agent.storage.swarm_work_pause import active_pause, assert_stopped, pause_targets

RESUME_TEXT = (
    "Resume the team work paused by the user. Inspect existing task state and deliverables first; "
    "continue the original assignment, preserve completed work, and never replay an external "
    "action whose outcome is unknown. Keep the original members and executor sessions."
)


async def control_work(plans, owner, sid, spec):
    action = spec["action"]
    async with plans.lock(sid):

        def prepare(db):
            def apply():
                team = group(db, owner, sid)
                plans.mutable(team, spec)
                pause = active_pause(db, sid)
                if action == "pause_work":
                    if pause:
                        raise DomainError("SWARM_WORK_ALREADY_PAUSED", 409)
                    targets = pause_targets(db, team)
                    main = row(
                        db,
                        "SELECT id FROM turns WHERE conversation_id=? AND state='running'",
                        (team["conversation_id"],),
                    )
                    pid = identity()
                    payload = {
                        "targets": targets,
                        "mainTurnId": main["id"] if main else None,
                        "conversationId": team["conversation_id"],
                    }
                    db.execute(
                        "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,'swarm.work.pause',?,?,?,'queued',?)",
                        (pid, sid, "swarm.work.pause:" + pid, encoded(payload), now_ms()),
                    )
                    for target in targets:
                        request_task_cancellation(db, owner, target["taskId"])
                    db.execute(
                        "UPDATE swarm_groups SET paused=1,revision=revision+1 WHERE id=?", (sid,)
                    )
                    team["revision"] += 1
                    changed(db, team)
                else:
                    if not pause:
                        raise DomainError("SWARM_WORK_NOT_PAUSED", 409)
                    assert_stopped(db, pause)
                    pid = pause["id"]
                return {
                    "id": sid,
                    "revision": team["revision"] + int(action == "resume_work"),
                    "action": action,
                    "pauseId": pid,
                }

            return receipt(
                db, owner, spec["commandKey"], {"swarmId": sid, **spec}, apply, swarm_id=sid
            )

        result = await plans.db.call(prepare, write=True)
        pause = await plans.db.call(
            lambda db: row(db, "SELECT * FROM jobs WHERE id=?", (result["pauseId"],))
        )
        # Replaying a completed command must never stop a later generation.
        if pause["state"] != "queued":
            return result
        payload = json.loads(pause["payload_json"])
        if action == "pause_work":
            if payload["mainTurnId"]:
                await plans.chat.interrupt(
                    owner,
                    payload["conversationId"],
                    "swarm.work.stop:" + pause["id"],
                    expected_turn_id=payload["mainTurnId"],
                    pause_id=pause["id"],
                )
        else:
            await plans.db.call(lambda db: assert_stopped(db, pause))
            for target in payload["targets"]:

                def needs_resume(db, target=target):
                    task = row(db, "SELECT state FROM tasks WHERE id=?", (target["taskId"],))
                    pending = row(
                        db,
                        "SELECT id FROM jobs WHERE kind='task.steer' AND aggregate_id=? AND state='queued'",
                        (target["taskId"],),
                    )
                    return task["state"] in {"cancelled", "interrupted", "failed"} and not pending

                if not await plans.db.call(needs_resume):
                    continue
                await plans.tasks.revisions.request(
                    owner,
                    target["taskId"],
                    RESUME_TEXT,
                    target["revision"],
                    "swarm.work.resume:" + pause["id"] + ":" + target["taskId"],
                )
            main = await plans.db.call(
                lambda db: row(db, "SELECT state FROM turns WHERE id=?", (payload["mainTurnId"],))
            )
            if main and main["state"] == "interrupted":
                await plans.chat.submit(
                    owner,
                    payload["conversationId"],
                    "swarm.work.resume:" + pause["id"],
                    RESUME_TEXT,
                )

            def finish(db):
                team = group(db, owner, sid)
                plans.mutable(team, spec)
                db.execute("UPDATE jobs SET state='done' WHERE id=?", (pause["id"],))
                db.execute(
                    "UPDATE swarm_groups SET paused=0,revision=revision+1 WHERE id=?", (sid,)
                )
                team["revision"] += 1
                changed(db, team)
                enqueue(db, sid, identity())

            await plans.db.call(finish, write=True)
    plans.wakeup.set()
    return result
