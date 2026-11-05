CREATE TABLE project_okr_mains(
 owner_id TEXT NOT NULL,
 project_id TEXT NOT NULL,
 conversation_id TEXT NOT NULL UNIQUE REFERENCES conversations(id),
 PRIMARY KEY(owner_id,project_id)
);
