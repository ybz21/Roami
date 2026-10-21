CREATE TABLE browser_tabs (
  resource_id TEXT PRIMARY KEY REFERENCES resources(id),
  browser_id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','closing','closed')),
  created_ms INTEGER NOT NULL,
  last_used_ms INTEGER NOT NULL,
  idle_since_ms INTEGER,
  retry_after_ms INTEGER NOT NULL DEFAULT 0,
  close_operation_id TEXT,
  close_receipt_json TEXT CHECK(close_receipt_json IS NULL OR json_valid(close_receipt_json)),
  closed_ms INTEGER,
  UNIQUE(browser_id,target_id)
);
CREATE INDEX browser_tabs_recycling ON browser_tabs(browser_id,state,idle_since_ms);
