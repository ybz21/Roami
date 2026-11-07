CREATE TABLE swarm_coordination_results(
 batch_id TEXT NOT NULL REFERENCES swarm_coordination_batches(id),
 delegation_id TEXT NOT NULL REFERENCES swarm_goal_delegations(id),
 receipt_id INTEGER NOT NULL REFERENCES events(id),
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json) AND json_type(payload_json)='object'),
 PRIMARY KEY(delegation_id,receipt_id)
);
CREATE INDEX swarm_coordination_result_batch ON swarm_coordination_results(batch_id,receipt_id);
CREATE TABLE swarm_result_observations(
 delegation_id TEXT NOT NULL REFERENCES swarm_goal_delegations(id),
 receipt_id INTEGER NOT NULL REFERENCES events(id),
 manifest_id TEXT NOT NULL REFERENCES prompt_manifests(id),
 source_json TEXT NOT NULL CHECK(json_valid(source_json) AND json_type(source_json)='object'),
 PRIMARY KEY(delegation_id,receipt_id,manifest_id)
);
CREATE TRIGGER swarm_coordination_result_scope BEFORE INSERT ON swarm_coordination_results BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_coordination_batches b JOIN swarm_goal_delegations d ON d.id=b.delegation_id
  JOIN swarm_groups g ON g.id=b.swarm_id JOIN events e ON e.id=NEW.receipt_id
  JOIN tasks t ON t.id=e.task_id JOIN task_attempts a ON a.id=json_extract(e.payload_json,'$.runId')
  JOIN swarm_work_items w ON w.task_id=t.id JOIN swarm_members m ON m.current_work_id=w.id
  WHERE b.id=NEW.batch_id AND d.id=NEW.delegation_id AND m.swarm_id=g.id
  AND e.kind='task.execution_result_recorded' AND e.conversation_id=g.conversation_id
  AND t.owner_id=g.owner_id AND t.origin_conversation_id=g.conversation_id
  AND a.task_id=t.id AND a.task_revision=t.revision
  AND json_extract(NEW.payload_json,'$.executionReceipt.receiptId')=e.id
  AND json_extract(NEW.payload_json,'$.memberId')=m.id
  AND json_extract(NEW.payload_json,'$.originMessageId')=t.origin_message_id
  AND EXISTS(SELECT 1 FROM json_each(d.member_ids_json) member WHERE member.value=m.id)
 ) THEN RAISE(ABORT,'SWARM_COORDINATION_SCOPE_CONFLICT') END;
END;
CREATE TRIGGER swarm_result_observation_scope BEFORE INSERT ON swarm_result_observations BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM prompt_manifests p JOIN turns t ON t.id=p.turn_id
  JOIN swarm_coordination_batches b ON b.turn_id=t.id
  JOIN swarm_goal_delegations d ON d.id=b.delegation_id
  JOIN swarm_groups g ON g.id=d.swarm_id JOIN events e ON e.id=NEW.receipt_id
  JOIN tasks task ON task.id=e.task_id JOIN swarm_work_items w ON w.task_id=task.id
  JOIN swarm_members member ON member.current_work_id=w.id AND member.swarm_id=g.id
  WHERE p.id=NEW.manifest_id AND d.id=NEW.delegation_id
  AND t.conversation_id=g.conversation_id AND e.conversation_id=g.conversation_id
  AND e.kind='task.execution_result_recorded'
  AND task.owner_id=g.owner_id AND task.origin_conversation_id=g.conversation_id
  AND EXISTS(SELECT 1 FROM json_each(d.member_ids_json) selected WHERE selected.value=member.id)
 ) THEN RAISE(ABORT,'SWARM_COORDINATION_SCOPE_CONFLICT') END;
END;
CREATE TRIGGER swarm_coordination_result_immutable BEFORE UPDATE ON swarm_coordination_results BEGIN
 SELECT RAISE(ABORT,'SWARM_COORDINATION_IMMUTABLE');
END;
CREATE TRIGGER swarm_result_observation_immutable BEFORE UPDATE ON swarm_result_observations BEGIN
 SELECT RAISE(ABORT,'SWARM_COORDINATION_IMMUTABLE');
END;
