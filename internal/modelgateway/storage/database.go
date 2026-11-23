package storage

import (
	"path/filepath"
	"slices"

	metadb "github.com/ybz21/Roami/internal/storage"
)

var schema = []metadb.Step{{Version: 1, Name: "local-model-gateway", SQL: `
CREATE TABLE gateway_configuration(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
CREATE TABLE gateway_calls(
 id TEXT PRIMARY KEY, day TEXT NOT NULL, timezone TEXT NOT NULL, role TEXT NOT NULL, model TEXT NOT NULL,
 session_id TEXT NOT NULL, request_id TEXT NOT NULL, started_ms INTEGER NOT NULL, finished_ms INTEGER,
 state TEXT NOT NULL, currency TEXT NOT NULL, price_json TEXT NOT NULL,
 input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cost_nano INTEGER,
 http_status INTEGER NOT NULL DEFAULT 0, error_code TEXT NOT NULL DEFAULT '', reconciliation TEXT NOT NULL DEFAULT ''
);
CREATE INDEX gateway_calls_day ON gateway_calls(day,started_ms);
`}, {Version: 2, Name: "model-catalog", SQL: `CREATE TABLE gateway_catalog(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);`}, {Version: 3, Name: "agent-gateway-attribution", SQL: `
ALTER TABLE gateway_calls ADD COLUMN agent_kind TEXT NOT NULL DEFAULT 'roami';
ALTER TABLE gateway_calls ADD COLUMN key_id TEXT NOT NULL DEFAULT '';
ALTER TABLE gateway_calls ADD COLUMN source_id TEXT NOT NULL DEFAULT '';
ALTER TABLE gateway_calls ADD COLUMN route_id TEXT NOT NULL DEFAULT '';
ALTER TABLE gateway_calls ADD COLUMN price_status TEXT NOT NULL DEFAULT 'priced';
UPDATE gateway_calls SET agent_kind=substr(role,5),key_id='legacy' WHERE role IN ('cli_opencode','cli_claude','cli_codex','cli_pi','cli_roami');
CREATE INDEX gateway_calls_agent_day ON gateway_calls(agent_kind,day,started_ms);
`}, {Version: 4, Name: "upstream-response-receipts", SQL: `
ALTER TABLE gateway_calls ADD COLUMN upstream_http_status INTEGER NOT NULL DEFAULT 0;
ALTER TABLE gateway_calls ADD COLUMN upstream_request_id TEXT NOT NULL DEFAULT '';
`}, {Version: 5, Name: "daily-usage-retention", SQL: `
CREATE TABLE gateway_daily_usage(
 day TEXT NOT NULL, timezone TEXT NOT NULL, role TEXT NOT NULL, model TEXT NOT NULL,
 currency TEXT NOT NULL, agent_kind TEXT NOT NULL, source TEXT NOT NULL,
 requests INTEGER NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
 cache_read_tokens INTEGER NOT NULL, cost_nano INTEGER NOT NULL,
 unknown INTEGER NOT NULL, usage_unknown INTEGER NOT NULL, failed INTEGER NOT NULL,
 PRIMARY KEY(day,timezone,role,model,currency,agent_kind,source),
 CHECK(typeof(requests)='integer' AND typeof(input_tokens)='integer' AND typeof(output_tokens)='integer'
  AND typeof(cache_read_tokens)='integer' AND typeof(cost_nano)='integer'
  AND typeof(unknown)='integer' AND typeof(usage_unknown)='integer' AND typeof(failed)='integer')
);
CREATE INDEX gateway_calls_retention ON gateway_calls(COALESCE(finished_ms,started_ms)) WHERE state!='pending';
`}, {Version: 6, Name: "daily-model-source-attribution", SQL: `
ALTER TABLE gateway_daily_usage RENAME TO gateway_daily_usage_v5;
CREATE TABLE gateway_daily_usage(
 day TEXT NOT NULL, timezone TEXT NOT NULL, role TEXT NOT NULL, model TEXT NOT NULL,
 currency TEXT NOT NULL, agent_kind TEXT NOT NULL, source TEXT NOT NULL,
 requests INTEGER NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
 cache_read_tokens INTEGER NOT NULL, cost_nano INTEGER NOT NULL,
 unknown INTEGER NOT NULL, usage_unknown INTEGER NOT NULL, failed INTEGER NOT NULL,
 source_id TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(day,timezone,role,model,currency,agent_kind,source,source_id),
 CHECK(typeof(requests)='integer' AND typeof(input_tokens)='integer' AND typeof(output_tokens)='integer'
  AND typeof(cache_read_tokens)='integer' AND typeof(cost_nano)='integer'
  AND typeof(unknown)='integer' AND typeof(usage_unknown)='integer' AND typeof(failed)='integer')
);
INSERT INTO gateway_daily_usage SELECT *,'' FROM gateway_daily_usage_v5;
DROP TABLE gateway_daily_usage_v5;
`}, {Version: 7, Name: "model-route-anchors", SQL: `CREATE TABLE gateway_route_anchors(model_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,anchor TEXT NOT NULL);`}, {Version: 8, Name: "gateway-observation-attribution", SQL: `
ALTER TABLE gateway_calls ADD COLUMN observation_request_id TEXT NOT NULL DEFAULT '';
CREATE INDEX gateway_calls_observation ON gateway_calls(observation_request_id) WHERE observation_request_id!='';
`}}

func Open(paths metadb.Paths) (*metadb.DB, error) {
	if _, err := paths.Ensure(); err != nil {
		return nil, err
	}
	return metadb.OpenManaged(paths, metadb.DatabaseDescriptor{ID: "model-gateway", Kind: "model-gateway", Owner: "go-model-gateway", Path: filepath.Join(paths.Database, "models", "gateway.db")}, schema, metadb.Options{})
}

func Migrations() []metadb.Step { return slices.Clone(schema) }
