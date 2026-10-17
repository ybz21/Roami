ALTER TABLE artifacts ADD COLUMN name TEXT NOT NULL DEFAULT 'artifact';
ALTER TABLE artifacts ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json));
CREATE INDEX artifacts_owner_task ON artifacts(owner_id,task_id,deleted_ms,created_ms DESC);
CREATE INDEX artifacts_owner_content ON artifacts(owner_id,sha256,deleted_ms);
