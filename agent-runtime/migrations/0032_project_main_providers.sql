CREATE UNIQUE INDEX project_okr_main_identity ON project_okr_mains(owner_id,project_id,conversation_id);
CREATE TABLE project_okr_main_providers(
 owner_id TEXT NOT NULL,
 project_id TEXT NOT NULL,
 conversation_id TEXT NOT NULL,
 generation INTEGER NOT NULL CHECK(generation>=1),
 executor TEXT NOT NULL CHECK(executor IN ('claude','codex')),
 model TEXT NOT NULL,
 launch_key TEXT NOT NULL UNIQUE,
 session_id TEXT NOT NULL UNIQUE,
 provider_id TEXT NOT NULL UNIQUE,
 binding_json TEXT NOT NULL,
 created_ms INTEGER NOT NULL,
 PRIMARY KEY(owner_id,project_id,generation),
 FOREIGN KEY(owner_id,project_id,conversation_id) REFERENCES project_okr_mains(owner_id,project_id,conversation_id)
);
