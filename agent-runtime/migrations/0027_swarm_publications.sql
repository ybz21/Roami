CREATE TABLE swarm_publication_items(
 id TEXT PRIMARY KEY,
 owner_id TEXT NOT NULL,
 project_id TEXT NOT NULL,
 swarm_id TEXT NOT NULL REFERENCES swarm_groups(id) ON DELETE CASCADE,
 delegation_id TEXT NOT NULL REFERENCES swarm_goal_delegations(id) ON DELETE CASCADE,
 member_id TEXT NOT NULL REFERENCES swarm_members(id),
 business_key TEXT NOT NULL CHECK(length(business_key) BETWEEN 1 AND 100),
 channel TEXT NOT NULL CHECK(channel IN ('x','bilibili')),
 created_turn_id TEXT NOT NULL REFERENCES turns(id),
 created_ms INTEGER NOT NULL,
 UNIQUE(owner_id,project_id,channel,business_key)
);
CREATE INDEX swarm_publication_project ON swarm_publication_items(owner_id,project_id,created_ms);
CREATE TRIGGER swarm_publication_item_scope BEFORE INSERT ON swarm_publication_items BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_groups g JOIN swarm_goal_delegations d ON d.swarm_id=g.id
  JOIN swarm_members m ON m.swarm_id=g.id JOIN turns t ON t.conversation_id=g.conversation_id
  JOIN conversations c ON c.id=t.conversation_id
  JOIN project_okr_mains p ON p.owner_id=g.owner_id AND p.project_id=g.scope_project_id
  WHERE g.id=NEW.swarm_id AND g.owner_id=NEW.owner_id AND g.scope_project_id=NEW.project_id
  AND p.conversation_id=c.id AND g.archived=0 AND g.paused=0 AND d.id=NEW.delegation_id
  AND d.revoked_ms IS NULL AND m.id=NEW.member_id AND EXISTS(
   SELECT 1 FROM json_each(d.member_ids_json) WHERE value=m.id
  ) AND t.id=NEW.created_turn_id AND t.state='running' AND t.branch_id=c.active_branch_id
  AND c.deleted_ms IS NULL
 ) THEN RAISE(ABORT,'PUBLICATION_PROJECT_SCOPE_CONFLICT') END;
END;
CREATE TRIGGER swarm_publication_item_immutable BEFORE UPDATE ON swarm_publication_items BEGIN
 SELECT RAISE(ABORT,'PUBLICATION_ITEM_IMMUTABLE');
END;

CREATE TABLE swarm_publication_versions(
 id TEXT PRIMARY KEY,
 item_id TEXT NOT NULL REFERENCES swarm_publication_items(id) ON DELETE CASCADE,
 sequence INTEGER NOT NULL CHECK(sequence>0),
 author_task_id TEXT NOT NULL REFERENCES tasks(id),
 author_revision INTEGER NOT NULL CHECK(author_revision>0),
 author_run_id TEXT NOT NULL REFERENCES task_attempts(id),
 account_identity TEXT,
 manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json) AND json_type(manifest_json)='object'),
 manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256)=64),
 content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64),
 created_turn_id TEXT NOT NULL REFERENCES turns(id),
 created_ms INTEGER NOT NULL,
 UNIQUE(item_id,sequence),
 UNIQUE(item_id,manifest_sha256)
);
CREATE INDEX swarm_publication_content ON swarm_publication_versions(content_sha256);
CREATE TRIGGER swarm_publication_version_author BEFORE INSERT ON swarm_publication_versions BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_publication_items p JOIN swarm_members m ON m.id=p.member_id
  JOIN swarm_member_work b ON b.member_id=m.id AND b.work_id=m.current_work_id
  JOIN swarm_work_items w ON w.id=b.work_id AND w.swarm_id=p.swarm_id
  JOIN tasks t ON t.id=w.task_id JOIN task_attempts a ON a.task_id=t.id AND a.task_revision=t.revision
  JOIN swarm_groups g ON g.id=p.swarm_id JOIN turns r ON r.conversation_id=g.conversation_id
  JOIN conversations c ON c.id=r.conversation_id
  WHERE p.id=NEW.item_id AND t.id=NEW.author_task_id AND t.revision=NEW.author_revision
  AND a.id=NEW.author_run_id AND t.owner_id=p.owner_id AND t.origin_conversation_id=g.conversation_id
  AND t.state='succeeded' AND a.state='succeeded' AND r.id=NEW.created_turn_id
  AND r.state='running' AND r.branch_id=c.active_branch_id AND c.deleted_ms IS NULL
 ) THEN RAISE(ABORT,'PUBLICATION_AUTHOR_NOT_CURRENT') END;
END;
CREATE TRIGGER swarm_publication_version_immutable BEFORE UPDATE ON swarm_publication_versions BEGIN
 SELECT RAISE(ABORT,'PUBLICATION_VERSION_IMMUTABLE');
END;

CREATE TABLE swarm_publication_reviews(
 id TEXT PRIMARY KEY,
 version_id TEXT NOT NULL REFERENCES swarm_publication_versions(id) ON DELETE CASCADE,
 turn_id TEXT NOT NULL REFERENCES turns(id),
 assistant_message_id TEXT NOT NULL REFERENCES messages(id),
 lease_epoch INTEGER NOT NULL CHECK(lease_epoch>0),
 decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')),
 proof_json TEXT NOT NULL CHECK(json_valid(proof_json) AND json_type(proof_json)='object'),
 feedback TEXT NOT NULL,
 created_ms INTEGER NOT NULL,
 UNIQUE(version_id,turn_id)
);
CREATE TRIGGER swarm_publication_review_scope BEFORE INSERT ON swarm_publication_reviews BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_publication_versions v JOIN swarm_publication_items p ON p.id=v.item_id
  JOIN swarm_groups g ON g.id=p.swarm_id JOIN turns t ON t.conversation_id=g.conversation_id
  JOIN conversations c ON c.id=t.conversation_id
  JOIN messages a ON a.turn_id=t.id AND a.conversation_id=c.id AND a.branch_id=t.branch_id
  WHERE v.id=NEW.version_id AND t.id=NEW.turn_id AND t.state='running'
  AND t.lease_epoch=NEW.lease_epoch AND t.branch_id=c.active_branch_id AND c.owner_id=p.owner_id
  AND c.deleted_ms IS NULL AND a.id=NEW.assistant_message_id AND a.role='assistant'
  AND a.deleted_ms IS NULL AND a.status!='deleted'
 ) THEN RAISE(ABORT,'PUBLICATION_MAIN_REQUIRED') END;
END;
CREATE TRIGGER swarm_publication_review_immutable BEFORE UPDATE ON swarm_publication_reviews BEGIN
 SELECT RAISE(ABORT,'PUBLICATION_REVIEW_IMMUTABLE');
END;

CREATE TABLE swarm_publication_source_files(
 artifact_id TEXT PRIMARY KEY REFERENCES artifacts(id) ON DELETE CASCADE,
 manifest_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
 manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256)=64),
 relative_path TEXT NOT NULL,
 source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
 source_size INTEGER NOT NULL CHECK(source_size>0),
 UNIQUE(manifest_artifact_id,relative_path)
);
CREATE TRIGGER swarm_publication_source_immutable BEFORE UPDATE ON swarm_publication_source_files BEGIN
 SELECT RAISE(ABORT,'PUBLICATION_SOURCE_IMMUTABLE');
END;
