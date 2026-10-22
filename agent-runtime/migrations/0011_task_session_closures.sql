CREATE TABLE task_session_closures (
  task_id TEXT PRIMARY KEY REFERENCES tasks(id),
  task_revision INTEGER NOT NULL,
  run_id TEXT NOT NULL REFERENCES task_attempts(id),
  launch_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('closing','closed','failed','unknown')),
  error_code TEXT,
  updated_ms INTEGER NOT NULL
);
