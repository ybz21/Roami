CREATE TABLE project_okr_conversations(
 conversation_id TEXT PRIMARY KEY REFERENCES conversations(id),
 owner_id TEXT NOT NULL, project_id TEXT NOT NULL
);
