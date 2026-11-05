ALTER TABLE swarm_groups ADD COLUMN member_protocol INTEGER NOT NULL DEFAULT 0;
CREATE TABLE swarm_members(
 id TEXT PRIMARY KEY, swarm_id TEXT NOT NULL REFERENCES swarm_groups(id),
 name TEXT NOT NULL, executor TEXT NOT NULL, duty TEXT NOT NULL,
 current_work_id TEXT UNIQUE REFERENCES swarm_work_items(id),
 created_ms INTEGER NOT NULL, legacy INTEGER NOT NULL DEFAULT 0,
 UNIQUE(swarm_id,name)
);
CREATE TABLE swarm_member_work(
 member_id TEXT NOT NULL REFERENCES swarm_members(id),
 work_id TEXT PRIMARY KEY REFERENCES swarm_work_items(id)
);
CREATE TABLE swarm_member_rounds(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 member_id TEXT NOT NULL REFERENCES swarm_members(id),
 task_id TEXT NOT NULL REFERENCES tasks(id), revision INTEGER NOT NULL CHECK(revision>0),
 source_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL, request_text TEXT,
 created_ms INTEGER NOT NULL, legacy INTEGER NOT NULL DEFAULT 0,
 UNIQUE(member_id,task_id,revision)
);
CREATE INDEX swarm_member_round_history ON swarm_member_rounds(member_id,id);
INSERT INTO swarm_members(id,swarm_id,name,executor,duty,created_ms,legacy)
 SELECT w.id,w.swarm_id,w.member_name,w.executor,w.title,g.created_ms,1
 FROM swarm_work_items w JOIN swarm_groups g ON g.id=w.swarm_id;
INSERT INTO swarm_member_work SELECT id,id FROM swarm_work_items;
UPDATE swarm_members SET current_work_id=id WHERE legacy=1;
INSERT INTO swarm_member_rounds(member_id,task_id,revision,created_ms,legacy)
 SELECT w.id,a.task_id,a.task_revision,COALESCE(MIN(a.started_ms),t.created_ms),1
 FROM swarm_work_items w JOIN tasks t ON t.id=w.task_id
 JOIN task_attempts a ON a.task_id=t.id GROUP BY w.id,a.task_id,a.task_revision;

CREATE TRIGGER swarm_member_work_insert_scope BEFORE INSERT ON swarm_member_work BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_members m JOIN swarm_work_items w ON w.swarm_id=m.swarm_id
  WHERE m.id=NEW.member_id AND w.id=NEW.work_id AND m.executor=w.executor
 ) THEN RAISE(ABORT,'SWARM_MEMBER_BINDING_CONFLICT') END;
END;
CREATE TRIGGER swarm_member_work_update_scope BEFORE UPDATE ON swarm_member_work BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_members m JOIN swarm_work_items w ON w.swarm_id=m.swarm_id
  WHERE m.id=NEW.member_id AND w.id=NEW.work_id AND m.executor=w.executor
 ) THEN RAISE(ABORT,'SWARM_MEMBER_BINDING_CONFLICT') END;
END;

CREATE TRIGGER swarm_member_current_scope BEFORE UPDATE OF current_work_id ON swarm_members
WHEN NEW.current_work_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_member_work b WHERE b.member_id=NEW.id AND b.work_id=NEW.current_work_id
 ) THEN RAISE(ABORT,'SWARM_MEMBER_BINDING_CONFLICT') END;
END;
