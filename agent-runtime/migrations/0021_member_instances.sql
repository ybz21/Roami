CREATE TABLE swarm_member_instances(
 id TEXT PRIMARY KEY,
 member_id TEXT NOT NULL UNIQUE REFERENCES swarm_members(id),
 owner_id TEXT NOT NULL,
 conversation_id TEXT NOT NULL UNIQUE REFERENCES conversations(id),
 branch_id TEXT NOT NULL UNIQUE REFERENCES branches(id),
 task_id TEXT UNIQUE REFERENCES tasks(id),
 created_ms INTEGER NOT NULL
);
CREATE TRIGGER member_instance_scope BEFORE INSERT ON swarm_member_instances BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_members m JOIN swarm_groups g ON g.id=m.swarm_id
  JOIN conversations c ON c.id=NEW.conversation_id JOIN branches b ON b.id=NEW.branch_id
  WHERE m.id=NEW.member_id AND m.executor='native' AND g.owner_id=NEW.owner_id
  AND c.owner_id=g.owner_id AND b.conversation_id=c.id AND c.id!=g.conversation_id
  AND NOT EXISTS(SELECT 1 FROM main_conversations h WHERE h.conversation_id=c.id)
  AND NOT EXISTS(SELECT 1 FROM project_okr_conversations p WHERE p.conversation_id=c.id)
 ) THEN RAISE(ABORT,'MEMBER_INSTANCE_BINDING_CONFLICT') END;
END;
CREATE TRIGGER member_instance_task_scope BEFORE UPDATE OF task_id ON swarm_member_instances
WHEN NEW.task_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_members m JOIN swarm_groups g ON g.id=m.swarm_id
  JOIN tasks t ON t.id=NEW.task_id JOIN native_sessions n ON n.task_id=t.id
  WHERE m.id=NEW.member_id AND t.owner_id=g.owner_id AND t.origin_conversation_id=g.conversation_id
  AND n.conversation_id=NEW.conversation_id AND n.branch_id=NEW.branch_id
 ) OR (OLD.task_id IS NOT NULL AND OLD.task_id!=NEW.task_id)
 THEN RAISE(ABORT,'MEMBER_INSTANCE_BINDING_CONFLICT') END;
END;
CREATE TRIGGER member_instance_no_home BEFORE INSERT ON main_conversations
WHEN EXISTS(SELECT 1 FROM swarm_member_instances i WHERE i.conversation_id=NEW.conversation_id)
BEGIN SELECT RAISE(ABORT,'CONVERSATION_IDENTITY_CONFLICT'); END;
CREATE TRIGGER member_instance_no_home_update BEFORE UPDATE OF conversation_id ON main_conversations
WHEN EXISTS(SELECT 1 FROM swarm_member_instances i WHERE i.conversation_id=NEW.conversation_id)
BEGIN SELECT RAISE(ABORT,'CONVERSATION_IDENTITY_CONFLICT'); END;
CREATE TRIGGER member_instance_no_project BEFORE INSERT ON project_okr_conversations
WHEN EXISTS(SELECT 1 FROM swarm_member_instances i WHERE i.conversation_id=NEW.conversation_id)
BEGIN SELECT RAISE(ABORT,'CONVERSATION_IDENTITY_CONFLICT'); END;
CREATE TRIGGER member_instance_no_project_main BEFORE INSERT ON project_okr_mains
WHEN EXISTS(SELECT 1 FROM swarm_member_instances i WHERE i.conversation_id=NEW.conversation_id)
BEGIN SELECT RAISE(ABORT,'CONVERSATION_IDENTITY_CONFLICT'); END;
CREATE TRIGGER member_instance_no_swarm_main BEFORE INSERT ON swarm_groups
WHEN EXISTS(SELECT 1 FROM swarm_member_instances i WHERE i.conversation_id=NEW.conversation_id)
BEGIN SELECT RAISE(ABORT,'CONVERSATION_IDENTITY_CONFLICT'); END;
INSERT INTO swarm_member_instances(id,member_id,owner_id,conversation_id,branch_id,task_id,created_ms)
 SELECT lower(hex(randomblob(16))),m.id,g.owner_id,n.conversation_id,n.branch_id,t.id,m.created_ms
 FROM swarm_members m JOIN swarm_groups g ON g.id=m.swarm_id
 JOIN swarm_work_items w ON w.id=m.current_work_id JOIN tasks t ON t.id=w.task_id
 JOIN native_sessions n ON n.task_id=t.id
 WHERE m.executor='native' AND t.owner_id=g.owner_id AND t.origin_conversation_id=g.conversation_id
 AND n.owner_id=g.owner_id;
CREATE TRIGGER member_instance_identity_immutable BEFORE UPDATE OF member_id,owner_id,conversation_id,branch_id ON swarm_member_instances
WHEN NEW.member_id!=OLD.member_id OR NEW.owner_id!=OLD.owner_id OR NEW.conversation_id!=OLD.conversation_id OR NEW.branch_id!=OLD.branch_id
BEGIN SELECT RAISE(ABORT,'MEMBER_INSTANCE_BINDING_CONFLICT'); END;
CREATE TRIGGER member_instance_task_immutable BEFORE UPDATE OF task_id ON swarm_member_instances
WHEN OLD.task_id IS NOT NULL AND NEW.task_id IS NOT OLD.task_id
BEGIN SELECT RAISE(ABORT,'MEMBER_INSTANCE_BINDING_CONFLICT'); END;
CREATE TRIGGER member_instance_no_project_update BEFORE UPDATE OF conversation_id ON project_okr_conversations
WHEN EXISTS(SELECT 1 FROM swarm_member_instances i WHERE i.conversation_id=NEW.conversation_id)
BEGIN SELECT RAISE(ABORT,'CONVERSATION_IDENTITY_CONFLICT'); END;
CREATE TRIGGER member_instance_no_project_main_update BEFORE UPDATE OF conversation_id ON project_okr_mains
WHEN EXISTS(SELECT 1 FROM swarm_member_instances i WHERE i.conversation_id=NEW.conversation_id)
BEGIN SELECT RAISE(ABORT,'CONVERSATION_IDENTITY_CONFLICT'); END;
CREATE TRIGGER member_instance_no_swarm_main_update BEFORE UPDATE OF conversation_id ON swarm_groups
WHEN EXISTS(SELECT 1 FROM swarm_member_instances i WHERE i.conversation_id=NEW.conversation_id)
BEGIN SELECT RAISE(ABORT,'CONVERSATION_IDENTITY_CONFLICT'); END;
CREATE TRIGGER member_instance_initial_task_scope BEFORE INSERT ON swarm_member_instances
WHEN NEW.task_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_members m JOIN swarm_groups g ON g.id=m.swarm_id
  JOIN tasks t ON t.id=NEW.task_id JOIN native_sessions n ON n.task_id=t.id
  WHERE m.id=NEW.member_id AND t.owner_id=g.owner_id AND t.origin_conversation_id=g.conversation_id
  AND n.owner_id=g.owner_id AND n.conversation_id=NEW.conversation_id AND n.branch_id=NEW.branch_id
 ) THEN RAISE(ABORT,'MEMBER_INSTANCE_BINDING_CONFLICT') END;
END;
