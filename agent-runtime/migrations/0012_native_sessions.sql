CREATE TABLE native_sessions (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id),
  conversation_id TEXT NOT NULL UNIQUE REFERENCES conversations(id),
  branch_id TEXT NOT NULL UNIQUE REFERENCES branches(id),
  owner_id TEXT NOT NULL,
  parent_session_id TEXT REFERENCES native_sessions(id),
  parent_conversation_id TEXT NOT NULL REFERENCES conversations(id),
  root_conversation_id TEXT NOT NULL REFERENCES conversations(id),
  created_ms INTEGER NOT NULL,
  last_seq INTEGER NOT NULL DEFAULT 0,
  flushed_seq INTEGER NOT NULL DEFAULT 0,
  archived_seq INTEGER NOT NULL DEFAULT 0,
  unarchived_bytes INTEGER NOT NULL DEFAULT 0,
  archive_error TEXT
);
CREATE INDEX native_sessions_owner ON native_sessions(owner_id,created_ms);
CREATE TABLE native_session_events (
  session_id TEXT NOT NULL REFERENCES native_sessions(id),
  seq INTEGER NOT NULL,
  event_id TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  payload_json TEXT CHECK(payload_json IS NULL OR json_valid(payload_json)),
  created_ms INTEGER NOT NULL,
  record_sha256 TEXT,
  PRIMARY KEY(session_id,seq)
);
CREATE TABLE native_session_segments (
  session_id TEXT NOT NULL REFERENCES native_sessions(id),
  first_seq INTEGER NOT NULL,
  last_seq INTEGER NOT NULL,
  filename TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  raw_sha256 TEXT NOT NULL,
  raw_bytes INTEGER NOT NULL,
  compressed_bytes INTEGER NOT NULL,
  created_ms INTEGER NOT NULL,
  PRIMARY KEY(session_id,first_seq)
);

CREATE TRIGGER native_message_insert AFTER INSERT ON messages WHEN NEW.status NOT IN ('pending','streaming') AND (json_type(NEW.content_json,'$._nativePayload') IS NULL OR NEW.deleted_ms IS NOT NULL OR NEW.status='deleted')
BEGIN
  UPDATE native_sessions SET last_seq=last_seq+1 WHERE branch_id=NEW.branch_id;
  INSERT INTO native_session_events(session_id,seq,event_id,kind,entity_id,payload_json,created_ms)
    SELECT id,last_seq,lower(hex(randomblob(16))),CASE WHEN NEW.deleted_ms IS NOT NULL OR NEW.status='deleted' THEN 'message.deleted' ELSE 'message.committed' END,NEW.id,json_object('messageId',NEW.id,'role',NEW.role,'content',CASE WHEN NEW.deleted_ms IS NOT NULL OR NEW.status='deleted' THEN NULL ELSE json(native_public(NEW.content_json)) END,'turnId',NEW.turn_id,'status',NEW.status),CAST(strftime('%s','now') AS INTEGER)*1000
    FROM native_sessions WHERE branch_id=NEW.branch_id;
END;

CREATE TRIGGER native_message_update AFTER UPDATE OF content_json,status,deleted_ms ON messages WHEN NEW.status NOT IN ('pending','streaming') AND (json_type(NEW.content_json,'$._nativePayload') IS NULL OR NEW.deleted_ms IS NOT NULL OR NEW.status='deleted') AND (NEW.content_json!=OLD.content_json OR NEW.status!=OLD.status OR NEW.deleted_ms IS NOT OLD.deleted_ms)
BEGIN
  UPDATE native_sessions SET last_seq=last_seq+1 WHERE branch_id=NEW.branch_id;
  INSERT INTO native_session_events(session_id,seq,event_id,kind,entity_id,payload_json,created_ms)
    SELECT id,last_seq,lower(hex(randomblob(16))),CASE WHEN NEW.deleted_ms IS NOT NULL OR NEW.status='deleted' THEN 'message.deleted' ELSE 'message.committed' END,NEW.id,json_object('messageId',NEW.id,'role',NEW.role,'content',CASE WHEN NEW.deleted_ms IS NOT NULL OR NEW.status='deleted' THEN NULL ELSE json(native_public(NEW.content_json)) END,'turnId',NEW.turn_id,'status',NEW.status),CAST(strftime('%s','now') AS INTEGER)*1000
    FROM native_sessions WHERE branch_id=NEW.branch_id;
END;

CREATE TRIGGER native_tool_insert AFTER INSERT ON tool_calls WHEN json_type(NEW.arguments_json,'$._nativePayload') IS NULL
BEGIN
  UPDATE native_sessions SET last_seq=last_seq+1 WHERE branch_id=(SELECT branch_id FROM turns WHERE id=NEW.turn_id);
  INSERT INTO native_session_events(session_id,seq,event_id,kind,entity_id,payload_json,created_ms)
    SELECT id,last_seq,lower(hex(randomblob(16))),'tool.'||NEW.state,NEW.id,json_object('callId',NEW.id,'turnId',NEW.turn_id,'toolName',NEW.tool_name,'arguments',json(native_public(NEW.arguments_json)),'effect',NEW.effect,'state',NEW.state,'resultMessageId',NEW.result_message_id),CAST(strftime('%s','now') AS INTEGER)*1000
    FROM native_sessions WHERE branch_id=(SELECT branch_id FROM turns WHERE id=NEW.turn_id);
END;

CREATE TRIGGER native_tool_update AFTER UPDATE OF state,arguments_json ON tool_calls WHEN json_type(NEW.arguments_json,'$._nativePayload') IS NULL AND (NEW.state!=OLD.state OR NEW.arguments_json!=OLD.arguments_json)
BEGIN
  UPDATE native_sessions SET last_seq=last_seq+1 WHERE branch_id=(SELECT branch_id FROM turns WHERE id=NEW.turn_id);
  INSERT INTO native_session_events(session_id,seq,event_id,kind,entity_id,payload_json,created_ms)
    SELECT id,last_seq,lower(hex(randomblob(16))),'tool.'||NEW.state,NEW.id,json_object('callId',NEW.id,'turnId',NEW.turn_id,'toolName',NEW.tool_name,'arguments',json(native_public(NEW.arguments_json)),'effect',NEW.effect,'state',NEW.state,'resultMessageId',NEW.result_message_id),CAST(strftime('%s','now') AS INTEGER)*1000
    FROM native_sessions WHERE branch_id=(SELECT branch_id FROM turns WHERE id=NEW.turn_id);
END;

CREATE TRIGGER native_turn_state AFTER UPDATE OF state ON turns WHEN NEW.state!=OLD.state
BEGIN
  UPDATE native_sessions SET last_seq=last_seq+1 WHERE branch_id=NEW.branch_id;
  INSERT INTO native_session_events(session_id,seq,event_id,kind,entity_id,payload_json,created_ms)
    SELECT id,last_seq,lower(hex(randomblob(16))),'turn.'||NEW.state,NEW.id,json_object('turnId',NEW.id,'state',NEW.state,'finishedMs',NEW.finished_ms),CAST(strftime('%s','now') AS INTEGER)*1000
    FROM native_sessions WHERE branch_id=NEW.branch_id;
END;

CREATE INDEX native_pending_events ON native_session_events(session_id,seq) WHERE payload_json IS NOT NULL;

CREATE TRIGGER native_task_state AFTER UPDATE OF state,target_json,revision ON tasks
WHEN NEW.state!=OLD.state OR NEW.target_json IS NOT OLD.target_json OR NEW.revision!=OLD.revision
BEGIN
  UPDATE native_sessions SET last_seq=last_seq+1 WHERE task_id=NEW.id;
  INSERT INTO native_session_events(session_id,seq,event_id,kind,entity_id,payload_json,created_ms)
    SELECT id,last_seq,lower(hex(randomblob(16))),'task.updated',NEW.id,json_object('taskId',NEW.id,'state',NEW.state,'revision',NEW.revision,'target',json(NEW.target_json)),CAST(strftime('%s','now') AS INTEGER)*1000 FROM native_sessions WHERE task_id=NEW.id;
END;
CREATE TRIGGER native_closure_state AFTER UPDATE OF state ON task_session_closures
WHEN NEW.state!=OLD.state
BEGIN
  UPDATE native_sessions SET last_seq=last_seq+1 WHERE task_id=NEW.task_id;
  INSERT INTO native_session_events(session_id,seq,event_id,kind,entity_id,payload_json,created_ms)
    SELECT id,last_seq,lower(hex(randomblob(16))),'session.'||NEW.state,NEW.task_id,json_object('taskId',NEW.task_id,'state',NEW.state),NEW.updated_ms FROM native_sessions WHERE task_id=NEW.task_id;
END;

CREATE TABLE native_storage_config (id INTEGER PRIMARY KEY CHECK(id=1), reference_key TEXT NOT NULL);
INSERT INTO native_storage_config VALUES(1,lower(hex(randomblob(32))));

CREATE TRIGGER native_context_ready AFTER UPDATE OF state ON context_snapshots WHEN NEW.state='ready' AND OLD.state!='ready'
BEGIN
  UPDATE native_sessions SET last_seq=last_seq+1 WHERE branch_id=NEW.branch_id;
  INSERT INTO native_session_events(session_id,seq,event_id,kind,entity_id,payload_json,created_ms)
    SELECT id,last_seq,lower(hex(randomblob(16))),'context.checkpoint',NEW.id,json_object('snapshotId',NEW.id,'cutSeq',NEW.cut_seq,'summary',json(native_public(NEW.summary_json))),NEW.created_ms FROM native_sessions WHERE branch_id=NEW.branch_id;
END;

CREATE INDEX native_turn_history ON turns(branch_id,created_ms DESC);
