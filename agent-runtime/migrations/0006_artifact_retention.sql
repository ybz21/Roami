ALTER TABLE artifacts ADD COLUMN purged_ms INTEGER;
CREATE INDEX artifacts_content_retention ON artifacts(sha256,deleted_ms,purged_ms);
CREATE INDEX artifacts_deleted_retention ON artifacts(deleted_ms,purged_ms,sha256) WHERE deleted_ms IS NOT NULL;
