"""SQLite schema ownership stays below repositories and workflow services."""

EVALUATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS rsi_schema (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS rsi_budgets (
 owner TEXT NOT NULL, day TEXT NOT NULL, tokens_limit INTEGER NOT NULL,
 episodes_limit INTEGER NOT NULL, tokens_reserved INTEGER NOT NULL DEFAULT 0,
 episodes_reserved INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner,day)
);
CREATE TABLE IF NOT EXISTS rsi_cycles (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, day TEXT NOT NULL,
 state TEXT NOT NULL, started_ms INTEGER NOT NULL, finished_ms INTEGER,
 heartbeat_ms INTEGER NOT NULL, manifest_json TEXT NOT NULL, report_json TEXT
);
CREATE INDEX IF NOT EXISTS rsi_cycles_owner ON rsi_cycles(owner,started_ms DESC);
CREATE TABLE IF NOT EXISTS rsi_trials (
 cycle_id TEXT NOT NULL REFERENCES rsi_cycles(id), arm TEXT NOT NULL,
 case_id TEXT NOT NULL, repetition INTEGER NOT NULL, record_json TEXT NOT NULL,
 PRIMARY KEY(cycle_id,arm,case_id,repetition)
);
CREATE TABLE IF NOT EXISTS rsi_preferences (
 owner TEXT PRIMARY KEY, revision INTEGER NOT NULL, value_json TEXT NOT NULL, updated_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rsi_machines (
 owner TEXT NOT NULL, id TEXT NOT NULL, profile_json TEXT NOT NULL, registered_ms INTEGER NOT NULL,
 PRIMARY KEY(owner,id)
);
CREATE TABLE IF NOT EXISTS rsi_suites (
 owner TEXT NOT NULL, id TEXT NOT NULL, path TEXT NOT NULL, content_hash TEXT NOT NULL,
 summary_json TEXT NOT NULL, registered_ms INTEGER NOT NULL, PRIMARY KEY(owner,id)
);
CREATE TABLE IF NOT EXISTS rsi_requests (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, machine_id TEXT NOT NULL, kind TEXT NOT NULL,
 state TEXT NOT NULL, created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL,
 claim TEXT, cycle_id TEXT, error_code TEXT, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rsi_releases (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, policy_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
 created_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rsi_release_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, release_id TEXT,
 action TEXT NOT NULL, policy_json TEXT NOT NULL, created_ms INTEGER NOT NULL,
 request_key TEXT NOT NULL, UNIQUE(owner,request_key)
);
CREATE TABLE IF NOT EXISTS rsi_bindings (
 owner TEXT NOT NULL, conversation_id TEXT NOT NULL, release_id TEXT, event_seq INTEGER,
 policy_json TEXT NOT NULL, created_ms INTEGER NOT NULL, PRIMARY KEY(owner,conversation_id)
);
"""


RESEARCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS rsi_research_settings (
 owner TEXT PRIMARY KEY, revision INTEGER NOT NULL, config_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rsi_actions (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL, subject TEXT NOT NULL,
 state TEXT NOT NULL, payload_json TEXT NOT NULL, result_json TEXT,
 created_ms INTEGER NOT NULL, due_ms INTEGER NOT NULL, lease TEXT, expires_ms INTEGER,
 error_code TEXT, UNIQUE(owner,kind,subject)
);
CREATE TABLE IF NOT EXISTS rsi_improvements (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, fingerprint TEXT NOT NULL,
 state TEXT NOT NULL, revision INTEGER NOT NULL, finding_json TEXT NOT NULL,
 data_json TEXT NOT NULL, updated_ms INTEGER NOT NULL, UNIQUE(owner,fingerprint)
);
CREATE TABLE IF NOT EXISTS rsi_improvement_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, improvement_id TEXT,
 action_id TEXT NOT NULL, event TEXT NOT NULL, data_json TEXT NOT NULL, created_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS rsi_verify_receipts ON rsi_improvement_events(
 owner,json_extract(data_json,'$.verification_context.source_hash'),created_ms
) WHERE event='verify.completed';
CREATE TABLE IF NOT EXISTS rsi_operation_costs (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, day TEXT NOT NULL, reserved INTEGER NOT NULL,
 state TEXT NOT NULL, result_json TEXT
);
CREATE TABLE IF NOT EXISTS rsi_semantic_reviews (
 owner TEXT NOT NULL, cycle_id TEXT NOT NULL, trial_key TEXT NOT NULL,
 review_json TEXT NOT NULL, PRIMARY KEY(owner,cycle_id,trial_key)
);
CREATE TABLE IF NOT EXISTS rsi_code_targets (
 owner TEXT PRIMARY KEY, revision INTEGER NOT NULL, release_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rsi_code_observations (
 owner TEXT NOT NULL, improvement_id TEXT NOT NULL, cycle_id TEXT NOT NULL,
 day TEXT NOT NULL, passed INTEGER NOT NULL, PRIMARY KEY(owner,improvement_id,cycle_id)
);
CREATE TABLE IF NOT EXISTS rsi_review_reports (
 owner TEXT NOT NULL, cycle_id TEXT NOT NULL, report_json TEXT NOT NULL,
 issue_json TEXT, created_ms INTEGER NOT NULL, PRIMARY KEY(owner,cycle_id)
);
CREATE TABLE IF NOT EXISTS rsi_report_items (
 owner TEXT NOT NULL, cycle_id TEXT NOT NULL, improvement_id TEXT NOT NULL,
 point_id TEXT NOT NULL, PRIMARY KEY(owner,cycle_id,improvement_id)
);
"""


PIPELINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS rsi_pipeline_settings(owner TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rsi_pipeline_runs(
 id TEXT PRIMARY KEY,owner TEXT NOT NULL,request_key TEXT NOT NULL,mode TEXT NOT NULL,state TEXT NOT NULL,
 created_ms INTEGER NOT NULL,updated_ms INTEGER NOT NULL,snapshot_json TEXT NOT NULL,summary_json TEXT,
 cycle_id TEXT,issue_json TEXT,lease TEXT,expires_ms INTEGER,UNIQUE(owner,request_key)
);
CREATE TABLE IF NOT EXISTS rsi_pipeline_nodes(
 run_id TEXT NOT NULL,node TEXT NOT NULL,attempt INTEGER NOT NULL,state TEXT NOT NULL,
 config_json TEXT NOT NULL,started_ms INTEGER,finished_ms INTEGER,error_code TEXT,
 PRIMARY KEY(run_id,node,attempt)
);
CREATE TABLE IF NOT EXISTS rsi_pipeline_cases(
 run_id TEXT NOT NULL,case_id TEXT NOT NULL,source_hash TEXT NOT NULL,result_json TEXT NOT NULL,
 PRIMARY KEY(run_id,case_id)
);
CREATE TABLE IF NOT EXISTS rsi_pipeline_issues(
 id TEXT PRIMARY KEY,owner TEXT NOT NULL,case_id TEXT NOT NULL,code TEXT NOT NULL,
 created_ms INTEGER NOT NULL,updated_ms INTEGER NOT NULL,UNIQUE(owner,case_id,code)
);
CREATE TABLE IF NOT EXISTS rsi_pipeline_observations(
 run_id TEXT NOT NULL,issue_id TEXT NOT NULL,status TEXT NOT NULL,evidence_json TEXT NOT NULL,
 PRIMARY KEY(run_id,issue_id)
);
CREATE TABLE IF NOT EXISTS rsi_pipeline_artifacts(
 id TEXT PRIMARY KEY,run_id TEXT NOT NULL,node TEXT NOT NULL,name TEXT NOT NULL,path TEXT NOT NULL,
 sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,UNIQUE(run_id,node,name)
);
CREATE TABLE IF NOT EXISTS rsi_pipeline_events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,node TEXT NOT NULL,state TEXT NOT NULL,
 detail TEXT,created_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rsi_pipeline_costs(
 id TEXT PRIMARY KEY,owner TEXT NOT NULL,run_id TEXT NOT NULL,reserved INTEGER NOT NULL,
 state TEXT NOT NULL,result_json TEXT
);
CREATE INDEX IF NOT EXISTS rsi_pipeline_observation_issue ON rsi_pipeline_observations(issue_id);
CREATE INDEX IF NOT EXISTS rsi_pipeline_run_owner ON rsi_pipeline_runs(owner,created_ms);
CREATE TABLE IF NOT EXISTS rsi_pipeline_effects(
 run_id TEXT PRIMARY KEY,state TEXT NOT NULL,receipt_json TEXT
);
"""
