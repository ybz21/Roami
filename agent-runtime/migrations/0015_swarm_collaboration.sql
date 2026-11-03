CREATE TABLE swarm_groups(
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL,
 conversation_id TEXT NOT NULL REFERENCES conversations(id), goal TEXT NOT NULL,
 target_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 paused INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
 created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL,
 UNIQUE(owner_id,name)
);
CREATE TABLE swarm_work_items(
 id TEXT PRIMARY KEY, swarm_id TEXT NOT NULL REFERENCES swarm_groups(id),
 member_name TEXT NOT NULL, executor TEXT NOT NULL, title TEXT NOT NULL,
 goal TEXT NOT NULL, acceptance TEXT NOT NULL, integration INTEGER NOT NULL DEFAULT 0,
 task_id TEXT UNIQUE REFERENCES tasks(id), dispatch_error TEXT,
 UNIQUE(swarm_id,member_name)
);
CREATE TABLE swarm_dependencies(
 work_id TEXT NOT NULL REFERENCES swarm_work_items(id),
 upstream_id TEXT NOT NULL REFERENCES swarm_work_items(id),
 task_revision INTEGER NOT NULL DEFAULT 1, artifact_id TEXT,
 PRIMARY KEY(work_id,upstream_id), CHECK(work_id!=upstream_id)
);
CREATE TABLE swarm_commands(
 owner_id TEXT NOT NULL, command_key TEXT NOT NULL, digest TEXT NOT NULL,
 receipt_json TEXT NOT NULL, PRIMARY KEY(owner_id,command_key)
);
CREATE TABLE swarm_posts(
 id INTEGER PRIMARY KEY AUTOINCREMENT, swarm_id TEXT NOT NULL REFERENCES swarm_groups(id),
 author TEXT NOT NULL, text TEXT NOT NULL, task_id TEXT REFERENCES tasks(id),
 created_ms INTEGER NOT NULL
);
CREATE INDEX swarm_groups_conversation ON swarm_groups(conversation_id);
CREATE INDEX swarm_work_group ON swarm_work_items(swarm_id);
CREATE INDEX swarm_posts_group ON swarm_posts(swarm_id,id);
ALTER TABLE swarm_posts ADD COLUMN turn_id TEXT REFERENCES turns(id);
ALTER TABLE swarm_posts ADD COLUMN delivery_json TEXT;
ALTER TABLE swarm_groups ADD COLUMN origin_message_id TEXT REFERENCES messages(id);
