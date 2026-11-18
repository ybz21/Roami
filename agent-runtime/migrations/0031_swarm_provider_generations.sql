ALTER TABLE swarm_members ADD COLUMN execution_generation INTEGER NOT NULL DEFAULT 1 CHECK(execution_generation>0);
UPDATE swarm_members SET execution_generation=MAX(1,COALESCE((SELECT MAX(w.execution_generation) FROM swarm_member_work b JOIN swarm_work_items w ON w.id=b.work_id WHERE b.member_id=swarm_members.id),1));
CREATE TABLE swarm_member_provider_generations(
 member_id TEXT NOT NULL REFERENCES swarm_members(id),
 generation INTEGER NOT NULL CHECK(generation>0),
 owner_id TEXT NOT NULL,
 swarm_id TEXT NOT NULL REFERENCES swarm_groups(id),
 launch_key TEXT NOT NULL UNIQUE,
 session_id TEXT NOT NULL UNIQUE,
 provider_id TEXT NOT NULL,
 executor TEXT NOT NULL,
 model TEXT NOT NULL,
 binding_json TEXT NOT NULL CHECK(json_valid(binding_json)),
 workspace_json TEXT NOT NULL CHECK(json_valid(workspace_json)),
 created_ms INTEGER NOT NULL,
 PRIMARY KEY(member_id,generation)
);
CREATE TRIGGER swarm_provider_scope BEFORE INSERT ON swarm_member_provider_generations BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_members m JOIN swarm_groups g ON g.id=m.swarm_id
  WHERE m.id=NEW.member_id AND m.swarm_id=NEW.swarm_id AND g.owner_id=NEW.owner_id
  AND g.scope_project_id IS NOT NULL AND m.executor=NEW.executor AND m.model=NEW.model
  AND m.execution_generation=NEW.generation
 ) OR EXISTS(
  SELECT 1 FROM swarm_member_provider_generations p WHERE p.provider_id=NEW.provider_id AND p.member_id!=NEW.member_id
 ) THEN RAISE(ABORT,'SWARM_PROVIDER_BINDING_CONFLICT') END;
END;
