CREATE TABLE conversation_search_pending (
  message_id TEXT PRIMARY KEY,
  generation INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX context_completed_activity ON turns(branch_id,COALESCE(finished_ms,created_ms) DESC)
  WHERE state='completed';
CREATE INDEX context_pending_turns ON turns(branch_id) WHERE state IN ('queued','running');
CREATE TABLE conversation_search_documents (
  message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
  source_sha256 TEXT NOT NULL
);
CREATE VIRTUAL TABLE conversation_search_fts USING fts5(message_id UNINDEXED, terms);
INSERT INTO conversation_search_pending(message_id)
  SELECT id FROM messages WHERE role IN ('user','assistant','tool') AND status IN ('completed','interrupted','failed');
CREATE TRIGGER conversation_search_insert AFTER INSERT ON messages
WHEN NEW.status IN ('completed','interrupted','failed') AND NEW.role IN ('user','assistant','tool')
BEGIN
  INSERT INTO conversation_search_pending(message_id) VALUES(NEW.id)
    ON CONFLICT(message_id) DO UPDATE SET generation=generation+1;
END;
CREATE TRIGGER conversation_search_update AFTER UPDATE OF content_json,status,deleted_ms ON messages
WHEN (NEW.status IN ('completed','interrupted','failed') OR OLD.status IN ('completed','interrupted','failed') OR NEW.deleted_ms IS NOT NULL OR NEW.status='deleted')
  AND (NEW.content_json!=OLD.content_json OR NEW.status!=OLD.status OR NEW.deleted_ms IS NOT OLD.deleted_ms)
BEGIN
  INSERT INTO conversation_search_pending(message_id) VALUES(NEW.id)
    ON CONFLICT(message_id) DO UPDATE SET generation=generation+1;
END;
CREATE TRIGGER conversation_search_delete AFTER DELETE ON messages
BEGIN
  DELETE FROM conversation_search_fts WHERE message_id=OLD.id;
  DELETE FROM conversation_search_pending WHERE message_id=OLD.id;
END;

CREATE TABLE context_briefs (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  branch_id TEXT NOT NULL REFERENCES branches(id),
  branch_epoch INTEGER NOT NULL,
  memory_epoch INTEGER NOT NULL,
  policy_version TEXT NOT NULL,
  source_count INTEGER NOT NULL,
  source_sha256 TEXT NOT NULL,
  items_json TEXT NOT NULL CHECK(json_valid(items_json)),
  created_ms INTEGER NOT NULL
);
CREATE INDEX context_briefs_branch ON context_briefs(branch_id,created_ms DESC);
CREATE TABLE period_summaries (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  branch_id TEXT NOT NULL REFERENCES branches(id),
  branch_epoch INTEGER NOT NULL,
  memory_epoch INTEGER NOT NULL,
  policy_version TEXT NOT NULL,
  day_key TEXT NOT NULL,
  timezone TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  sources_json TEXT NOT NULL CHECK(json_valid(sources_json)),
  body TEXT NOT NULL,
  created_ms INTEGER NOT NULL,
  UNIQUE(branch_id,branch_epoch,memory_epoch,policy_version,day_key,timezone,source_sha256)
);
