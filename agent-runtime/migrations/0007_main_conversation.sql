CREATE TABLE main_conversations (
  owner_id TEXT PRIMARY KEY REFERENCES owner_versions(owner_id),
  conversation_id TEXT NOT NULL UNIQUE REFERENCES conversations(id),
  created_ms INTEGER NOT NULL
);
