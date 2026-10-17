ALTER TABLE deliveries ADD COLUMN claim_token TEXT;
ALTER TABLE deliveries ADD COLUMN claim_until_ms INTEGER;
ALTER TABLE deliveries ADD COLUMN category TEXT;
ALTER TABLE deliveries ADD COLUMN result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json));
ALTER TABLE deliveries ADD COLUMN updated_ms INTEGER;
CREATE TABLE notification_delivery_cursors (
  owner_id TEXT PRIMARY KEY,
  event_cursor INTEGER NOT NULL DEFAULT 0
);
INSERT INTO notification_delivery_cursors(owner_id,event_cursor)
SELECT DISTINCT owner_id,(SELECT COALESCE(MAX(id),0) FROM events) FROM conversations;
CREATE INDEX deliveries_claims ON deliveries(state,claim_until_ms);

INSERT OR IGNORE INTO channel_bindings(id,conversation_id,channel_kind,route_json,created_ms)
SELECT 'agent.app:' || c.id,c.id,'im','{"kind":"app"}',CAST(strftime('%s','now') AS INTEGER)*1000
FROM conversations c WHERE c.deleted_ms IS NULL
AND NOT EXISTS(SELECT 1 FROM task_attempts a JOIN branches b ON b.id=a.native_branch_id WHERE b.conversation_id=c.id);
