CREATE TABLE notification_preferences (
  owner_id TEXT PRIMARY KEY,
  settings_json TEXT NOT NULL CHECK(json_valid(settings_json)),
  updated_ms INTEGER NOT NULL
);
CREATE TABLE reminder_schedules (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  request_key TEXT NOT NULL,
  spec_json TEXT NOT NULL CHECK(json_valid(spec_json)),
  next_due_ms INTEGER,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
  created_ms INTEGER NOT NULL,
  updated_ms INTEGER NOT NULL,
  UNIQUE(owner_id,request_key)
);
CREATE INDEX reminder_schedules_due ON reminder_schedules(enabled,next_due_ms);
CREATE TABLE reminder_firings (
  schedule_id TEXT NOT NULL REFERENCES reminder_schedules(id),
  due_ms INTEGER NOT NULL,
  event_id INTEGER NOT NULL REFERENCES events(id),
  skipped_count INTEGER NOT NULL DEFAULT 0,
  created_ms INTEGER NOT NULL,
  PRIMARY KEY(schedule_id,due_ms)
);
CREATE TABLE notification_send_windows (
  owner_id TEXT NOT NULL,
  event_id INTEGER NOT NULL REFERENCES events(id),
  category TEXT NOT NULL CHECK(category IN ('task_result','decision','reminder','suggestion')),
  started_ms INTEGER NOT NULL,
  PRIMARY KEY(owner_id,event_id)
);
CREATE INDEX notification_send_windows_rate ON notification_send_windows(owner_id,category,started_ms);
