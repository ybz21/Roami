ALTER TABLE project_okr_main_providers RENAME TO project_okr_main_providers_previous;
CREATE TABLE project_okr_main_providers(
 owner_id TEXT NOT NULL,
 project_id TEXT NOT NULL,
 conversation_id TEXT NOT NULL,
 generation INTEGER NOT NULL CHECK(generation>=1),
 executor TEXT NOT NULL CHECK(executor IN ('claude','codex')),
 model TEXT NOT NULL,
 launch_key TEXT NOT NULL UNIQUE,
 session_id TEXT NOT NULL UNIQUE,
 provider_id TEXT NOT NULL,
 binding_json TEXT NOT NULL,
 created_ms INTEGER NOT NULL,
 PRIMARY KEY(owner_id,project_id,generation),
 FOREIGN KEY(owner_id,project_id,conversation_id) REFERENCES project_okr_mains(owner_id,project_id,conversation_id)
);
INSERT INTO project_okr_main_providers SELECT * FROM project_okr_main_providers_previous;
DROP TABLE project_okr_main_providers_previous;
CREATE INDEX project_okr_main_provider_owner ON project_okr_main_providers(provider_id,owner_id,project_id,conversation_id);
CREATE TRIGGER project_okr_main_provider_owner_insert
BEFORE INSERT ON project_okr_main_providers
WHEN EXISTS(
 SELECT 1 FROM project_okr_main_providers p WHERE p.provider_id=NEW.provider_id
 AND (p.owner_id!=NEW.owner_id OR p.project_id!=NEW.project_id OR p.conversation_id!=NEW.conversation_id)
)
BEGIN
 SELECT RAISE(ABORT, 'PROJECT_MAIN_PROVIDER_OWNERSHIP_CONFLICT');
END;
CREATE TRIGGER project_okr_main_provider_owner_update
BEFORE UPDATE OF provider_id,owner_id,project_id,conversation_id ON project_okr_main_providers
WHEN NEW.provider_id!=OLD.provider_id OR NEW.owner_id!=OLD.owner_id
 OR NEW.project_id!=OLD.project_id OR NEW.conversation_id!=OLD.conversation_id
BEGIN
 SELECT RAISE(ABORT, 'PROJECT_MAIN_PROVIDER_OWNERSHIP_CONFLICT');
END;
