package modelgateway

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"path/filepath"
	"time"

	"github.com/google/uuid"
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
`}, {Version: 7, Name: "model-route-anchors", SQL: `CREATE TABLE gateway_route_anchors(model_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,anchor TEXT NOT NULL);`}}

type Ledger struct {
	paths metadb.Paths
	db    *metadb.DB
	now   func() time.Time
}

func Open(paths metadb.Paths) (*Ledger, error) {
	if _, err := paths.Ensure(); err != nil {
		return nil, err
	}
	db, err := metadb.OpenManaged(paths, metadb.DatabaseDescriptor{ID: "model-gateway", Kind: "model-gateway", Owner: "go-model-gateway", Path: filepath.Join(paths.Database, "models", "gateway.db")}, schema, metadb.Options{})
	if err != nil {
		return nil, err
	}
	l := &Ledger{db: db, now: time.Now, paths: paths}
	return l, nil
}

// Called only after the service socket lock is held; another owner's calls stay intact.
func (l *Ledger) Recover() error {
	return l.db.Tx(func(tx *sql.Tx) error {
		zero, _ := json.Marshal(ModelPricing{})
		_, err := tx.Exec(`UPDATE gateway_calls SET state=CASE WHEN price_json=? AND price_status='priced' THEN 'failed' ELSE 'unknown' END,cost_nano=CASE WHEN price_json=? AND price_status='priced' THEN 0 ELSE NULL END,finished_ms=?,error_code='MODEL_PROXY_INTERRUPTED' WHERE state='pending'`, string(zero), string(zero), l.now().UnixMilli())
		return err
	})
}

type queryRow interface{ QueryRow(string, ...any) *sql.Row }

func configuration(q queryRow) (Configuration, error) {
	var raw string
	err := q.QueryRow(`SELECT value FROM gateway_configuration WHERE id=1`).Scan(&raw)
	if err == sql.ErrNoRows {
		return defaultConfiguration(), nil
	}
	if err != nil {
		return Configuration{}, err
	}
	return decodeConfiguration([]byte(raw))
}

func (l *Ledger) Configuration() (Configuration, error) { return configuration(l.db) }

func (l *Ledger) Configure(c Configuration) error {
	if err := c.validate(); err != nil {
		return err
	}
	return l.db.Tx(func(tx *sql.Tx) error {
		previous, err := configuration(tx)
		if err != nil {
			return err
		}
		if c.Pricing.Sources == nil {
			c.Pricing.Sources = previous.Pricing.Sources
		}
		if previous.Currency != c.Currency || previous.Timezone != c.Timezone {
			var count int
			// Reinterpreting an existing accounting period could bypass its daily limit.
			err = tx.QueryRow(`SELECT (SELECT count(*) FROM gateway_calls WHERE state='pending' OR state='unknown' OR day>=?) + (SELECT COALESCE(sum(requests),0) FROM gateway_daily_usage WHERE unknown>0 OR day>=?)`, l.now().UTC().Add(-48*time.Hour).Format("2006-01-02"), l.now().UTC().Add(-48*time.Hour).Format("2006-01-02")).Scan(&count)
			if err != nil {
				return err
			}
			if count > 0 {
				return fmt.Errorf("MODEL_PROXY_CURRENCY_MISMATCH")
			}
		}
		raw, err := json.Marshal(c)
		if err != nil {
			return err
		}
		_, err = tx.Exec(`INSERT INTO gateway_configuration(id,value) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value`, string(raw))
		return err
	})
}

type Call struct {
	upstream    upstreamReceipt
	PriceStatus string       `json:"priceStatus"`
	AgentKind   string       `json:"agentKind"`
	KeyID       string       `json:"keyId"`
	SourceID    string       `json:"sourceId"`
	RouteID     string       `json:"routeId"`
	ID          string       `json:"id"`
	Day         string       `json:"day"`
	Timezone    string       `json:"timezone"`
	Role        string       `json:"role"`
	Model       string       `json:"model"`
	Session     string       `json:"sessionId"`
	Request     string       `json:"requestId"`
	Started     int64        `json:"startedMs"`
	State       string       `json:"state"`
	Currency    string       `json:"currency"`
	Price       ModelPricing `json:"price"`
}

type CallAttribution struct {
	AgentKind, KeyID, SourceID, RouteID string
	Free                                bool
}
type gatewayKeyContext struct{}

func (l *Ledger) Admit(role, model, session, request string, attribution ...CallAttribution) (Call, error) {
	call := Call{ID: uuid.NewString(), Role: role, Model: model, Session: session, Request: request, Started: l.now().UnixMilli(), State: "pending"}
	call.AgentKind = "roami"
	if len(attribution) > 0 {
		a := attribution[0]
		call.AgentKind, call.KeyID, call.SourceID, call.RouteID = a.AgentKind, a.KeyID, a.SourceID, a.RouteID
	}
	err := l.db.Tx(func(tx *sql.Tx) error {
		c, err := configuration(tx)
		if err != nil {
			return err
		}
		zone, err := time.LoadLocation(c.Timezone)
		if err != nil {
			return err
		}
		call.Day, call.Timezone, call.Currency = l.now().In(zone).Format("2006-01-02"), c.Timezone, c.Currency
		var priced bool
		call.Price, priced = c.Pricing.exitPriceAt(call.RouteID, call.SourceID, model, time.UnixMilli(call.Started))
		if len(attribution) > 0 && attribution[0].Free {
			if _, explicit := c.Pricing.lookup(call.RouteID); !explicit {
				call.Price = ModelPricing{}
				priced = true
			}
		}
		call.PriceStatus = "priced"
		if !priced {
			call.PriceStatus = "unpriced"
		}
		if c.DailyLimit != nil {
			var spent, pending int64
			err := tx.QueryRow(`SELECT COALESCE(SUM(cost_nano),0),COALESCE(SUM(state='pending'),0) FROM gateway_calls WHERE day=?`, call.Day).Scan(&spent, &pending)
			if err != nil {
				return err
			}
			if pending > 0 {
				return fmt.Errorf("MODEL_PROXY_USAGE_PENDING")
			}
			if spent >= nanoAmount(*c.DailyLimit) {
				return fmt.Errorf("MODEL_PROXY_DAILY_LIMIT")
			}
		}
		price, err := json.Marshal(call.Price)
		if err != nil {
			return err
		}
		_, err = tx.Exec(`INSERT INTO gateway_calls(id,day,timezone,role,model,session_id,request_id,started_ms,state,currency,price_json,agent_kind,key_id,source_id,route_id,price_status) VALUES(?,?,?,?,?,?,?,?,'pending',?,?,?,?,?,?,?)`, call.ID, call.Day, call.Timezone, role, model, session, request, call.Started, call.Currency, string(price), call.AgentKind, call.KeyID, call.SourceID, call.RouteID, call.PriceStatus)
		return err
	})
	return call, err
}

func (l *Ledger) Settle(call Call, usage *Usage, status int, code string, notSent bool) error {
	var input, output, cached, cost any
	state := "unknown"
	if usage != nil {
		input, output, cached, cost = usage.Input, usage.Output, usage.Cached, costNano(call.Price, *usage)
		state = "known"
		if call.PriceStatus == "unpriced" {
			cost = nil
			state = "unknown"
			if code == "" {
				code = "MODEL_GATEWAY_PRICE_MISSING"
			}
		}
	} else if notSent || call.Price == (ModelPricing{}) && call.PriceStatus != "unpriced" {
		cost, state = int64(0), "known"
	}
	if code != "" && state == "known" && !(status >= 200 && status < 300 && code == "MODEL_PROXY_USAGE_UNKNOWN") {
		state = "failed"
	}
	return l.db.Tx(func(tx *sql.Tx) error {
		_, err := tx.Exec(`UPDATE gateway_calls SET state=?,finished_ms=?,input_tokens=?,output_tokens=?,cache_read_tokens=?,cost_nano=?,http_status=?,error_code=?,upstream_http_status=?,upstream_request_id=? WHERE id=? AND state='pending'`, state, l.now().UnixMilli(), input, output, cached, cost, status, code, call.upstream.status, call.upstream.request, call.ID)
		return err
	})
}

func (l *Ledger) Reconcile(id string, amount float64, reason string) error {
	if !validAmount(amount) || len(reason) == 0 || len(reason) > 500 {
		return fmt.Errorf("INVALID_MODEL_PROXY_CONFIG")
	}
	return l.db.Tx(func(tx *sql.Tx) error {
		result, err := tx.Exec(`UPDATE gateway_calls SET state='known',cost_nano=?,reconciliation=? WHERE id=? AND state='unknown'`, nanoAmount(amount), reason, id)
		if err != nil {
			return err
		}
		count, err := result.RowsAffected()
		if err == nil && count != 1 {
			return fmt.Errorf("MODEL_GATEWAY_CALL_NOT_UNKNOWN")
		}
		return err
	})
}
