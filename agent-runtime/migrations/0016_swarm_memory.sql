CREATE TABLE swarm_memories(
 swarm_id TEXT PRIMARY KEY REFERENCES swarm_groups(id),
 content TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL,
 updated_ms INTEGER NOT NULL, author TEXT NOT NULL
);
ALTER TABLE swarm_work_items ADD COLUMN deliverables_json TEXT NOT NULL DEFAULT '[]';
