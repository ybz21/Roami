-- Candidate schema for design review. Not installed in production.
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 1000;

CREATE TABLE schema_meta (
  version INTEGER PRIMARY KEY,
  applied_ms INTEGER NOT NULL
);
CREATE TABLE owner_versions (
  owner_id TEXT PRIMARY KEY,
  profile_version INTEGER NOT NULL DEFAULT 1,
  memory_epoch INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE conversations (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  title TEXT NOT NULL,
  active_branch_id TEXT REFERENCES branches(id),
  created_ms INTEGER NOT NULL,
  updated_ms INTEGER NOT NULL,
  deleted_ms INTEGER
);
CREATE INDEX conversations_owner ON conversations(owner_id, updated_ms DESC);
CREATE TABLE branches (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  parent_branch_id TEXT REFERENCES branches(id),
  fork_message_id TEXT REFERENCES messages(id),
  head_seq INTEGER NOT NULL DEFAULT 0,
  epoch INTEGER NOT NULL DEFAULT 1,
  context_version INTEGER NOT NULL DEFAULT 1,
  created_ms INTEGER NOT NULL,
  CHECK ((parent_branch_id IS NULL) = (fork_message_id IS NULL))
);
CREATE TABLE requests (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  request_key TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  turn_id TEXT REFERENCES turns(id),
  accepted_ms INTEGER NOT NULL,
  UNIQUE(owner_id, request_key)
);
CREATE TABLE turns (
  id TEXT PRIMARY KEY,
  request_id TEXT UNIQUE REFERENCES requests(id),
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  branch_id TEXT NOT NULL REFERENCES branches(id),
  trigger_kind TEXT NOT NULL CHECK(trigger_kind IN ('user','completion','continuation')),
  state TEXT NOT NULL CHECK(state IN ('queued','running','completed','interrupted','failed')),
  revision INTEGER NOT NULL DEFAULT 1,
  lease_owner TEXT,
  lease_until_ms INTEGER,
  lease_epoch INTEGER NOT NULL DEFAULT 0,
  created_ms INTEGER NOT NULL,
  finished_ms INTEGER
);
CREATE UNIQUE INDEX one_running_turn ON turns(branch_id) WHERE state='running';
CREATE TABLE messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  branch_id TEXT NOT NULL REFERENCES branches(id),
  seq INTEGER NOT NULL,
  turn_id TEXT REFERENCES turns(id),
  role TEXT NOT NULL CHECK(role IN ('user','assistant','tool','system','event')),
  content_json TEXT NOT NULL CHECK(json_valid(content_json)),
  status TEXT NOT NULL CHECK(status IN ('pending','streaming','completed','interrupted','failed','deleted')),
  reply_to_id TEXT REFERENCES messages(id),
  created_ms INTEGER NOT NULL,
  deleted_ms INTEGER,
  UNIQUE(branch_id, seq)
);
CREATE INDEX messages_turn ON messages(turn_id, seq);
CREATE TABLE channel_bindings (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  channel_kind TEXT NOT NULL CHECK(channel_kind IN ('web','im')),
  route_json TEXT NOT NULL CHECK(json_valid(route_json)),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
  created_ms INTEGER NOT NULL
);
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  origin_conversation_id TEXT NOT NULL REFERENCES conversations(id),
  origin_branch_id TEXT NOT NULL REFERENCES branches(id),
  origin_message_id TEXT NOT NULL REFERENCES messages(id),
  parent_task_id TEXT REFERENCES tasks(id),
  revision INTEGER NOT NULL DEFAULT 1,
  intent_json TEXT NOT NULL CHECK(json_valid(intent_json)),
  target_json TEXT CHECK(target_json IS NULL OR json_valid(target_json)),
  state TEXT NOT NULL CHECK(state IN ('preparing','queued','running','waiting_user','verifying','succeeded','failed','cancelling','cancelled','interrupted')),
  budget_json TEXT NOT NULL CHECK(json_valid(budget_json)),
  created_ms INTEGER NOT NULL,
  updated_ms INTEGER NOT NULL
);
CREATE INDEX tasks_origin ON tasks(origin_conversation_id, created_ms);
CREATE TABLE task_attempts (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  task_revision INTEGER NOT NULL,
  attempt_no INTEGER NOT NULL,
  executor_kind TEXT NOT NULL CHECK(executor_kind IN ('native','cli')),
  launch_id TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL CHECK(state IN ('accepted','starting','running','stopping','succeeded','failed','cancelled','interrupted','unknown')),
  node_id TEXT,
  session_id TEXT,
  agent_conversation_id TEXT,
  native_branch_id TEXT REFERENCES branches(id),
  result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
  lease_epoch INTEGER NOT NULL,
  started_ms INTEGER,
  finished_ms INTEGER,
  UNIQUE(task_id, task_revision, attempt_no)
);
CREATE TABLE tool_calls (
  id TEXT PRIMARY KEY,
  turn_id TEXT NOT NULL REFERENCES turns(id),
  assistant_message_id TEXT NOT NULL REFERENCES messages(id),
  result_message_id TEXT REFERENCES messages(id),
  tool_name TEXT NOT NULL,
  arguments_json TEXT NOT NULL CHECK(json_valid(arguments_json)),
  effect TEXT NOT NULL CHECK(effect IN ('read','write')),
  state TEXT NOT NULL CHECK(state IN ('planned','running','succeeded','failed','cancelled','unknown')),
  idempotency_key TEXT NOT NULL UNIQUE,
  resource_key TEXT,
  lease_epoch INTEGER NOT NULL DEFAULT 0,
  created_ms INTEGER NOT NULL,
  updated_ms INTEGER NOT NULL
);
CREATE TABLE resources (
  id TEXT PRIMARY KEY,
  node_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  resource_key TEXT NOT NULL,
  owner_task_id TEXT REFERENCES tasks(id),
  lease_epoch INTEGER NOT NULL DEFAULT 0,
  lease_until_ms INTEGER,
  created_by_task INTEGER NOT NULL DEFAULT 0 CHECK(created_by_task IN (0,1)),
  UNIQUE(node_id, kind, resource_key)
);
CREATE TABLE artifacts (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  task_id TEXT REFERENCES tasks(id),
  message_id TEXT REFERENCES messages(id),
  path TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  created_ms INTEGER NOT NULL,
  deleted_ms INTEGER
);
CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  turn_id TEXT REFERENCES turns(id),
  message_id TEXT REFERENCES messages(id),
  task_id TEXT REFERENCES tasks(id),
  event_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
  created_ms INTEGER NOT NULL
);
CREATE INDEX events_conversation ON events(conversation_id,id);
CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  dedupe_key TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
  state TEXT NOT NULL CHECK(state IN ('queued','running','done','failed')),
  attempts INTEGER NOT NULL DEFAULT 0,
  available_ms INTEGER NOT NULL,
  lease_owner TEXT,
  lease_until_ms INTEGER,
  lease_epoch INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX jobs_ready ON jobs(state,available_ms);
CREATE TABLE deliveries (
  id TEXT PRIMARY KEY,
  event_id INTEGER NOT NULL REFERENCES events(id),
  channel_id TEXT NOT NULL REFERENCES channel_bindings(id),
  state TEXT NOT NULL CHECK(state IN ('pending','sending','delivered','failed','unknown')),
  attempts INTEGER NOT NULL DEFAULT 0,
  retry_ms INTEGER,
  external_message_id TEXT,
  UNIQUE(event_id,channel_id)
);
CREATE TABLE memory_records (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('fact','decision','preference','summary')),
  project_id TEXT,
  conversation_id TEXT REFERENCES conversations(id),
  task_id TEXT REFERENCES tasks(id),
  day_key TEXT,
  timezone TEXT,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  search_tokens TEXT NOT NULL,
  canonical_key TEXT,
  state TEXT NOT NULL CHECK(state IN ('candidate','active','conflict','superseded','deleted')),
  revision INTEGER NOT NULL DEFAULT 1,
  supersedes_id TEXT REFERENCES memory_records(id),
  valid_from_ms INTEGER NOT NULL,
  valid_until_ms INTEGER,
  expires_ms INTEGER,
  source_watermark INTEGER,
  created_ms INTEGER NOT NULL,
  updated_ms INTEGER NOT NULL
);
CREATE INDEX memory_owner_scope ON memory_records(owner_id,project_id,conversation_id,task_id,state);
CREATE INDEX memory_day ON memory_records(owner_id,day_key,timezone);
CREATE TABLE memory_sources (
  memory_id TEXT NOT NULL REFERENCES memory_records(id),
  source_key TEXT NOT NULL,
  message_id TEXT REFERENCES messages(id),
  event_id INTEGER REFERENCES events(id),
  artifact_id TEXT REFERENCES artifacts(id),
  source_sha256 TEXT NOT NULL,
  PRIMARY KEY(memory_id,source_key),
  CHECK((message_id IS NOT NULL)+(event_id IS NOT NULL)+(artifact_id IS NOT NULL)=1)
);
CREATE TABLE memory_edges (
  parent_id TEXT NOT NULL REFERENCES memory_records(id),
  derived_id TEXT NOT NULL REFERENCES memory_records(id),
  PRIMARY KEY(parent_id,derived_id),
  CHECK(parent_id<>derived_id)
);
CREATE TABLE memory_tombstones (
  owner_id TEXT NOT NULL,
  source_fingerprint TEXT NOT NULL,
  canonical_key TEXT NOT NULL,
  created_ms INTEGER NOT NULL,
  PRIMARY KEY(owner_id,source_fingerprint,canonical_key)
);
CREATE VIRTUAL TABLE memory_fts USING fts5(record_id UNINDEXED, tokens, tokenize='unicode61');
CREATE TRIGGER memory_fts_insert AFTER INSERT ON memory_records WHEN new.state='active' BEGIN
  INSERT INTO memory_fts(record_id,tokens) VALUES(new.id,new.search_tokens);
END;
CREATE TRIGGER memory_fts_update AFTER UPDATE ON memory_records BEGIN
  DELETE FROM memory_fts WHERE record_id=old.id;
  INSERT INTO memory_fts(record_id,tokens) SELECT new.id,new.search_tokens WHERE new.state='active';
END;
CREATE TRIGGER memory_fts_delete AFTER DELETE ON memory_records BEGIN
  DELETE FROM memory_fts WHERE record_id=old.id;
END;
CREATE TABLE memory_embeddings (
  memory_id TEXT NOT NULL REFERENCES memory_records(id),
  revision INTEGER NOT NULL,
  model_key TEXT NOT NULL,
  dimensions INTEGER NOT NULL,
  vector BLOB NOT NULL,
  PRIMARY KEY(memory_id,revision,model_key)
);
CREATE TABLE day_summaries (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  day_key TEXT NOT NULL,
  timezone TEXT NOT NULL,
  scope_key TEXT NOT NULL,
  source_watermark INTEGER NOT NULL,
  memory_id TEXT NOT NULL REFERENCES memory_records(id),
  counts_json TEXT NOT NULL CHECK(json_valid(counts_json)),
  revision INTEGER NOT NULL,
  UNIQUE(owner_id,day_key,timezone,scope_key)
);
CREATE TABLE context_snapshots (
  id TEXT PRIMARY KEY,
  branch_id TEXT NOT NULL REFERENCES branches(id),
  cut_seq INTEGER NOT NULL,
  ancestry_sha256 TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  branch_epoch INTEGER NOT NULL,
  policy_version TEXT NOT NULL,
  memory_epoch INTEGER NOT NULL,
  summary_json TEXT NOT NULL CHECK(json_valid(summary_json)),
  state TEXT NOT NULL CHECK(state IN ('building','ready','invalid')),
  created_ms INTEGER NOT NULL
);
CREATE INDEX snapshots_branch ON context_snapshots(branch_id,state,cut_seq DESC);
CREATE TABLE prompt_manifests (
  id TEXT PRIMARY KEY,
  turn_id TEXT NOT NULL REFERENCES turns(id),
  attempt_no INTEGER NOT NULL,
  provider_key TEXT NOT NULL,
  model_key TEXT NOT NULL,
  serializer_version TEXT NOT NULL,
  prefix_sha256 TEXT NOT NULL,
  snapshot_id TEXT REFERENCES context_snapshots(id),
  memory_epoch INTEGER NOT NULL,
  parts_json TEXT NOT NULL CHECK(json_valid(parts_json)),
  usage_json TEXT CHECK(usage_json IS NULL OR json_valid(usage_json)),
  created_ms INTEGER NOT NULL,
  UNIQUE(turn_id,attempt_no)
);
CREATE TABLE context_omissions (
  owner_id TEXT NOT NULL,
  message_id TEXT NOT NULL REFERENCES messages(id),
  source_memory_id TEXT REFERENCES memory_records(id),
  reason TEXT NOT NULL,
  created_ms INTEGER NOT NULL,
  PRIMARY KEY(owner_id,message_id)
);

-- Version metadata is read by the unified backup manifest.
INSERT INTO schema_meta(version, applied_ms) VALUES (1, 0);
