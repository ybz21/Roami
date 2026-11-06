CREATE TABLE swarm_groups_scoped(
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL,
 conversation_id TEXT NOT NULL REFERENCES conversations(id), goal TEXT NOT NULL,
 target_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 paused INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
 created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL,
 origin_message_id TEXT REFERENCES messages(id), member_protocol INTEGER NOT NULL DEFAULT 0,
 scope_project_id TEXT CHECK(scope_project_id IS NULL OR length(scope_project_id)>0),
 FOREIGN KEY(owner_id,scope_project_id) REFERENCES project_okr_mains(owner_id,project_id)
);
INSERT INTO swarm_groups_scoped
 SELECT g.id,g.owner_id,g.name,g.conversation_id,g.goal,g.target_json,g.revision,g.paused,
 g.archived,g.created_ms,g.updated_ms,g.origin_message_id,g.member_protocol,
 (SELECT p.project_id FROM project_okr_mains p
  JOIN project_okr_conversations b ON b.conversation_id=p.conversation_id
   AND b.owner_id=p.owner_id AND b.project_id=p.project_id
  JOIN conversations c ON c.id=p.conversation_id AND c.owner_id=p.owner_id
  WHERE p.owner_id=g.owner_id AND p.conversation_id=g.conversation_id
   AND json_extract(CASE WHEN json_valid(g.target_json) THEN g.target_json ELSE '{}' END,'$.kind')='project'
   AND p.project_id=json_extract(g.target_json,'$.projectId')
   AND NOT EXISTS(SELECT 1 FROM main_conversations h WHERE h.conversation_id=p.conversation_id)
   AND NOT EXISTS(SELECT 1 FROM native_sessions n WHERE n.conversation_id=p.conversation_id)
   AND NOT EXISTS(SELECT 1 FROM task_attempts a JOIN branches b ON b.id=a.native_branch_id WHERE b.conversation_id=p.conversation_id)
   AND NOT EXISTS(SELECT 1 FROM swarm_member_instances i WHERE i.conversation_id=p.conversation_id))
 FROM swarm_groups g;
DROP TABLE swarm_groups;
ALTER TABLE swarm_groups_scoped RENAME TO swarm_groups;
CREATE UNIQUE INDEX swarm_groups_scope_name ON swarm_groups(owner_id,COALESCE(scope_project_id,''),name);

CREATE TABLE swarm_commands_scoped(
 owner_id TEXT NOT NULL, command_key TEXT NOT NULL, digest TEXT NOT NULL,
 receipt_json TEXT NOT NULL, scope_project_id TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(owner_id,scope_project_id,command_key)
);
INSERT INTO swarm_commands_scoped
 SELECT c.owner_id,c.command_key,c.digest,c.receipt_json,COALESCE(g.scope_project_id,'')
 FROM swarm_commands c LEFT JOIN swarm_groups g ON g.owner_id=c.owner_id
 AND g.id=COALESCE(
  json_extract(CASE WHEN json_valid(c.receipt_json) THEN c.receipt_json ELSE '{}' END,'$.swarmId'),
  json_extract(CASE WHEN json_valid(c.receipt_json) THEN c.receipt_json ELSE '{}' END,'$.id'));
DROP TABLE swarm_commands;
ALTER TABLE swarm_commands_scoped RENAME TO swarm_commands;

ALTER TABLE swarm_posts ADD COLUMN delivery_key TEXT;

CREATE TRIGGER swarm_project_scope_insert BEFORE INSERT ON swarm_groups
WHEN NEW.scope_project_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM project_okr_mains p JOIN project_okr_conversations b ON b.conversation_id=p.conversation_id
   AND b.owner_id=p.owner_id AND b.project_id=p.project_id
  WHERE p.owner_id=NEW.owner_id AND p.project_id=NEW.scope_project_id AND p.conversation_id=NEW.conversation_id
   AND json_extract(NEW.target_json,'$.kind')='project'
   AND json_extract(NEW.target_json,'$.projectId')=p.project_id
 ) THEN RAISE(ABORT,'SWARM_PROJECT_SCOPE_CONFLICT') END;
END;
CREATE TRIGGER swarm_project_scope_update BEFORE UPDATE OF scope_project_id,owner_id,conversation_id,target_json ON swarm_groups
BEGIN
 SELECT CASE WHEN (OLD.scope_project_id IS NOT NULL AND
  (NEW.scope_project_id IS NOT OLD.scope_project_id OR NEW.owner_id!=OLD.owner_id OR NEW.conversation_id!=OLD.conversation_id))
 OR (NEW.scope_project_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM project_okr_mains p JOIN project_okr_conversations b ON b.conversation_id=p.conversation_id
   AND b.owner_id=p.owner_id AND b.project_id=p.project_id
  WHERE p.owner_id=NEW.owner_id AND p.project_id=NEW.scope_project_id AND p.conversation_id=NEW.conversation_id
   AND json_extract(NEW.target_json,'$.kind')='project'
   AND json_extract(NEW.target_json,'$.projectId')=p.project_id
 )) THEN RAISE(ABORT,'SWARM_PROJECT_SCOPE_CONFLICT') END;
END;
