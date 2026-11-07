CREATE TABLE swarm_goal_delegations(
 id TEXT PRIMARY KEY,
 swarm_id TEXT NOT NULL REFERENCES swarm_groups(id),
 revision INTEGER NOT NULL CHECK(revision>0),
 source_message_id TEXT NOT NULL REFERENCES messages(id),
 source_quote TEXT NOT NULL,
 source_sha256 TEXT NOT NULL,
 source_messages_json TEXT NOT NULL CHECK(json_valid(source_messages_json) AND json_type(source_messages_json)='array'),
 member_ids_json TEXT NOT NULL CHECK(json_valid(member_ids_json) AND json_type(member_ids_json)='array'),
 created_ms INTEGER NOT NULL,
 revoked_ms INTEGER,
 revoked_by_message_id TEXT REFERENCES messages(id),
 UNIQUE(swarm_id,revision),
 CHECK((revoked_ms IS NULL)=(revoked_by_message_id IS NULL))
);
CREATE UNIQUE INDEX swarm_goal_delegation_active ON swarm_goal_delegations(swarm_id)
 WHERE revoked_ms IS NULL;
CREATE TRIGGER swarm_goal_delegation_source BEFORE INSERT ON swarm_goal_delegations BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM messages m JOIN turns t ON t.id=m.turn_id
  JOIN swarm_groups g ON g.id=NEW.swarm_id JOIN conversations c ON c.id=g.conversation_id
  WHERE m.id=NEW.source_message_id AND m.conversation_id=g.conversation_id
  AND t.conversation_id=m.conversation_id AND t.trigger_kind='user' AND m.role='user'
  AND c.owner_id=g.owner_id AND g.scope_project_id IS NOT NULL
  AND m.deleted_ms IS NULL AND m.status!='deleted' AND c.deleted_ms IS NULL
  AND json_type(native_content(m.content_json),'$.scheduled') IS NULL
 ) THEN RAISE(ABORT,'SWARM_DELEGATION_SOURCE_REQUIRED') END;
END;

CREATE TABLE swarm_coordination_batches(
 id TEXT PRIMARY KEY,
 swarm_id TEXT NOT NULL REFERENCES swarm_groups(id),
 delegation_id TEXT NOT NULL REFERENCES swarm_goal_delegations(id),
 turn_id TEXT NOT NULL UNIQUE REFERENCES turns(id),
 created_ms INTEGER NOT NULL
);
CREATE TABLE swarm_coordination_inputs(
 inbox_id INTEGER PRIMARY KEY REFERENCES swarm_inbox(id),
 batch_id TEXT NOT NULL REFERENCES swarm_coordination_batches(id),
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json) AND json_type(payload_json)='object')
);
CREATE INDEX swarm_coordination_batch_inputs ON swarm_coordination_inputs(batch_id,inbox_id);
CREATE TRIGGER swarm_coordination_batch_scope BEFORE INSERT ON swarm_coordination_batches BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_goal_delegations d JOIN swarm_groups g ON g.id=d.swarm_id
  JOIN turns t ON t.id=NEW.turn_id JOIN conversations c ON c.id=g.conversation_id
  WHERE d.id=NEW.delegation_id AND d.swarm_id=NEW.swarm_id AND d.revoked_ms IS NULL
  AND t.conversation_id=g.conversation_id AND t.branch_id=c.active_branch_id
  AND t.trigger_kind='continuation' AND t.state='queued' AND g.paused=0 AND g.archived=0
 ) THEN RAISE(ABORT,'SWARM_COORDINATION_SCOPE_CONFLICT') END;
END;
CREATE TRIGGER swarm_coordination_input_scope BEFORE INSERT ON swarm_coordination_inputs BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_coordination_batches b JOIN swarm_goal_delegations d ON d.id=b.delegation_id
  JOIN swarm_groups g ON g.id=b.swarm_id JOIN swarm_inbox i ON i.id=NEW.inbox_id
  JOIN swarm_post_routes r ON r.post_id=i.post_id
  WHERE b.id=NEW.batch_id AND i.main_conversation_id=g.conversation_id
  AND r.swarm_id=g.id AND r.author_kind='member' AND i.handled_post_id IS NULL
  AND EXISTS(SELECT 1 FROM json_each(d.member_ids_json) m WHERE m.value=r.author_member_id)
 ) THEN RAISE(ABORT,'SWARM_COORDINATION_SCOPE_CONFLICT') END;
END;
CREATE TRIGGER swarm_coordination_batch_immutable BEFORE UPDATE ON swarm_coordination_batches BEGIN
 SELECT RAISE(ABORT,'SWARM_COORDINATION_IMMUTABLE');
END;
CREATE TRIGGER swarm_coordination_input_immutable BEFORE UPDATE ON swarm_coordination_inputs BEGIN
 SELECT RAISE(ABORT,'SWARM_COORDINATION_IMMUTABLE');
END;
CREATE TRIGGER swarm_goal_delegation_immutable
 BEFORE UPDATE OF swarm_id,revision,source_message_id,source_quote,source_sha256,source_messages_json,member_ids_json,created_ms
 ON swarm_goal_delegations BEGIN
 SELECT RAISE(ABORT,'SWARM_DELEGATION_IMMUTABLE');
END;
CREATE TRIGGER swarm_goal_delegation_revocation BEFORE UPDATE OF revoked_ms,revoked_by_message_id
 ON swarm_goal_delegations WHEN NEW.revoked_ms IS NOT OLD.revoked_ms OR NEW.revoked_by_message_id IS NOT OLD.revoked_by_message_id BEGIN
 SELECT CASE WHEN OLD.revoked_ms IS NOT NULL OR NEW.revoked_ms IS NULL OR NOT EXISTS(
  SELECT 1 FROM messages m JOIN turns t ON t.id=m.turn_id JOIN swarm_groups g ON g.id=OLD.swarm_id
  WHERE m.id=NEW.revoked_by_message_id AND m.conversation_id=g.conversation_id
  AND t.conversation_id=m.conversation_id AND t.trigger_kind='user' AND m.role='user'
  AND m.deleted_ms IS NULL AND m.status!='deleted'
  AND json_type(native_content(m.content_json),'$.scheduled') IS NULL
 ) THEN RAISE(ABORT,'SWARM_DELEGATION_SOURCE_REQUIRED') END;
END;
