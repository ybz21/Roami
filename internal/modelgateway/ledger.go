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
`}}

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
		_, err := tx.Exec(`UPDATE gateway_calls SET state=CASE WHEN price_json=? THEN 'failed' ELSE 'unknown' END,cost_nano=CASE WHEN price_json=? THEN 0 ELSE NULL END,finished_ms=?,error_code='MODEL_PROXY_INTERRUPTED' WHERE state='pending'`, string(zero), string(zero), l.now().UnixMilli())
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
		if previous.Currency != c.Currency || previous.Timezone != c.Timezone {
			var count int
			// Reinterpreting an existing accounting period could bypass its daily limit.
			err = tx.QueryRow(`SELECT count(*) FROM gateway_calls WHERE state='pending' OR state='unknown' OR day>=?`, l.now().UTC().Add(-48*time.Hour).Format("2006-01-02")).Scan(&count)
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
	ID       string       `json:"id"`
	Day      string       `json:"day"`
	Timezone string       `json:"timezone"`
	Role     string       `json:"role"`
	Model    string       `json:"model"`
	Session  string       `json:"sessionId"`
	Request  string       `json:"requestId"`
	Started  int64        `json:"startedMs"`
	State    string       `json:"state"`
	Currency string       `json:"currency"`
	Price    ModelPricing `json:"price"`
}

func (l *Ledger) Admit(role, model, session, request string) (Call, error) {
	call := Call{ID: uuid.NewString(), Role: role, Model: model, Session: session, Request: request, Started: l.now().UnixMilli(), State: "pending"}
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
		call.Price = c.Pricing.Lookup(model)
		if c.DailyLimit != nil {
			var spent, unknown, pending int64
			err := tx.QueryRow(`SELECT COALESCE(SUM(cost_nano),0),COALESCE(SUM(state='unknown'),0),COALESCE(SUM(state='pending'),0) FROM gateway_calls WHERE day=?`, call.Day).Scan(&spent, &unknown, &pending)
			if err != nil {
				return err
			}
			if unknown > 0 {
				return fmt.Errorf("MODEL_PROXY_USAGE_UNKNOWN")
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
		_, err = tx.Exec(`INSERT INTO gateway_calls(id,day,timezone,role,model,session_id,request_id,started_ms,state,currency,price_json) VALUES(?,?,?,?,?,?,?,?,'pending',?,?)`, call.ID, call.Day, call.Timezone, role, model, session, request, call.Started, call.Currency, string(price))
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
	} else if notSent || call.Price == (ModelPricing{}) {
		cost, state = int64(0), "known"
	}
	if code != "" && state == "known" && !(status >= 200 && status < 300 && code == "MODEL_PROXY_USAGE_UNKNOWN") {
		state = "failed"
	}
	return l.db.Tx(func(tx *sql.Tx) error {
		_, err := tx.Exec(`UPDATE gateway_calls SET state=?,finished_ms=?,input_tokens=?,output_tokens=?,cache_read_tokens=?,cost_nano=?,http_status=?,error_code=? WHERE id=? AND state='pending'`, state, l.now().UnixMilli(), input, output, cached, cost, status, code, call.ID)
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
