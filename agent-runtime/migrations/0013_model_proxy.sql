CREATE TABLE model_proxy_calls (
  id TEXT PRIMARY KEY,
  day TEXT NOT NULL,
  timezone TEXT NOT NULL,
  role TEXT NOT NULL,
  model TEXT NOT NULL,
  started_ms INTEGER NOT NULL,
  finished_ms INTEGER,
  state TEXT NOT NULL CHECK(state IN ('pending','known','unknown','failed')),
  prices_json TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  cache_read_tokens INTEGER,
  cost_nano INTEGER,
  error_code TEXT
);
CREATE INDEX model_proxy_calls_day ON model_proxy_calls(day, started_ms);
