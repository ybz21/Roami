ALTER TABLE resources ADD COLUMN owner_id TEXT;
ALTER TABLE resources ADD COLUMN owner_run_id TEXT REFERENCES task_attempts(id);
ALTER TABLE resources ADD COLUMN state TEXT NOT NULL DEFAULT 'idle' CHECK(state IN ('idle','held','pausing','paused','quarantined'));
ALTER TABLE resources ADD COLUMN scene_epoch INTEGER NOT NULL DEFAULT 0;
CREATE TABLE resource_observations (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES resources(id),
  task_id TEXT NOT NULL REFERENCES tasks(id),
  run_id TEXT NOT NULL REFERENCES task_attempts(id),
  lease_epoch INTEGER NOT NULL,
  scene_epoch INTEGER NOT NULL,
  signature TEXT NOT NULL,
  body_json TEXT NOT NULL CHECK(json_valid(body_json)),
  captured_ms INTEGER NOT NULL
);
CREATE INDEX resource_observations_latest ON resource_observations(resource_id,captured_ms DESC,id);
CREATE TABLE resource_actions (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES resources(id),
  task_id TEXT NOT NULL REFERENCES tasks(id),
  run_id TEXT NOT NULL REFERENCES task_attempts(id),
  lease_epoch INTEGER NOT NULL,
  observation_id TEXT NOT NULL REFERENCES resource_observations(id),
  idempotency_key TEXT NOT NULL UNIQUE,
  payload_sha256 TEXT NOT NULL,
  action_json TEXT NOT NULL CHECK(json_valid(action_json)),
  state TEXT NOT NULL CHECK(state IN ('running','succeeded','failed','unknown')),
  result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
  created_ms INTEGER NOT NULL,
  updated_ms INTEGER NOT NULL
);
CREATE INDEX resource_actions_pending ON resource_actions(resource_id,state);
