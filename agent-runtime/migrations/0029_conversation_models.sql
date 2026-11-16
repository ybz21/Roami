CREATE TABLE conversation_models (
  conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  free_only INTEGER NOT NULL DEFAULT 0 CHECK(free_only IN (0,1))
);
