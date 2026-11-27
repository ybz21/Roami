package accounting

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	metadb "github.com/ybz21/Roami/internal/storage"
)

type Ledger struct {
	db  *metadb.DB
	now func() time.Time
}

func New(db *metadb.DB, now func() time.Time) *Ledger {
	return &Ledger{db: db, now: now}
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
		return DefaultConfiguration(), nil
	}
	if err != nil {
		return Configuration{}, err
	}
	return decodeConfiguration([]byte(raw))
}

func (l *Ledger) Configuration() (Configuration, error) { return configuration(l.db) }

func (l *Ledger) Configure(c Configuration) error { return l.ConfigureScope(c, "") }

func (l *Ledger) ConfigureScope(c Configuration, scope string) error {
	if err := c.Validate(); err != nil {
		return err
	}
	return l.db.Tx(func(tx *sql.Tx) error {
		previous, err := configuration(tx)
		if err != nil {
			return err
		}
		switch scope {
		case "pricing":
			c.Currency, c.Timezone, c.DailyLimit = previous.Currency, previous.Timezone, previous.DailyLimit
			c.Pricing.Sources = previous.Pricing.Sources
		case "limits":
			c.Pricing = previous.Pricing
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
	upstreamStatus    int
	upstreamRequestID string
	PriceStatus       string       `json:"priceStatus"`
	AgentKind         string       `json:"agentKind"`
	KeyID             string       `json:"keyId"`
	SourceID          string       `json:"sourceId"`
	RouteID           string       `json:"routeId"`
	ID                string       `json:"id"`
	Day               string       `json:"day"`
	Timezone          string       `json:"timezone"`
	Role              string       `json:"role"`
	Model             string       `json:"model"`
	Session           string       `json:"sessionId"`
	Request           string       `json:"requestId"`
	Started           int64        `json:"startedMs"`
	State             string       `json:"state"`
	Currency          string       `json:"currency"`
	Price             ModelPricing `json:"price"`
}

func (c *Call) RecordUpstream(status int, requestID string) {
	c.upstreamStatus = status
	c.upstreamRequestID = requestID
}

type CallAttribution struct {
	AgentKind, KeyID, SourceID, RouteID, ObservationRequestID string
	Free                                                      bool
	PricingRevision                                           string
}

var ErrNotConfirmedFree = errors.New("MODEL_GATEWAY_NOT_CONFIRMED_FREE")

func (l *Ledger) Admit(role, model, session, request string, attribution ...CallAttribution) (Call, error) {
	return l.admit(role, model, session, request, false, attribution...)
}

func (l *Ledger) AdmitConfirmedFree(role, model, session, request string, attribution CallAttribution) (Call, error) {
	return l.admit(role, model, session, request, true, attribution)
}

func (l *Ledger) admit(role, model, session, request string, requireFree bool, attribution ...CallAttribution) (Call, error) {
	call := Call{ID: uuid.NewString(), Role: role, Model: model, Session: session, Request: request, Started: l.now().UnixMilli(), State: "pending"}
	call.AgentKind = "roami"
	var observationID string
	if len(attribution) > 0 {
		a := attribution[0]
		call.AgentKind, call.KeyID, call.SourceID, call.RouteID = a.AgentKind, a.KeyID, a.SourceID, a.RouteID
		observationID = a.ObservationRequestID
	}
	err := l.db.Tx(func(tx *sql.Tx) error {
		c, err := configuration(tx)
		if err != nil {
			return err
		}
		if len(attribution) > 0 && attribution[0].Free && attribution[0].PricingRevision != "" && attribution[0].PricingRevision != PricingRevision(c) {
			return fmt.Errorf("MODEL_GATEWAY_ROUTE_CHANGED")
		}
		zone, err := time.LoadLocation(c.Timezone)
		if err != nil {
			return err
		}
		call.Day, call.Timezone, call.Currency = l.now().In(zone).Format("2006-01-02"), c.Timezone, c.Currency
		var priced bool
		call.Price, priced = c.Pricing.ExitPriceAt(call.RouteID, call.SourceID, model, time.UnixMilli(call.Started))
		if len(attribution) > 0 && attribution[0].Free {
			if _, explicit := c.Pricing.MatchingPrice(call.RouteID); !explicit {
				call.Price = ModelPricing{}
				priced = true
			}
		}
		call.PriceStatus = "priced"
		if !priced {
			call.PriceStatus = "unpriced"
		}
		confirmedFree := len(attribution) > 0 && attribution[0].Free && attribution[0].PricingRevision != "" &&
			priced && call.Price == (ModelPricing{})
		if requireFree && !confirmedFree {
			return ErrNotConfirmedFree
		}
		price, err := json.Marshal(call.Price)
		if err != nil {
			return err
		}
		if c.DailyLimit != nil && !confirmedFree {
			var spent, pending int64
			zero, _ := json.Marshal(ModelPricing{})
			err := tx.QueryRow(`SELECT COALESCE(SUM(cost_nano),0),COALESCE(SUM(state='pending' AND
				(price_status!='priced' OR price_json IS NOT ?)),0) FROM gateway_calls WHERE day=?`, string(zero), call.Day).Scan(&spent, &pending)
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
		_, err = tx.Exec(`INSERT INTO gateway_calls(id,day,timezone,role,model,session_id,request_id,started_ms,state,currency,price_json,agent_kind,key_id,source_id,route_id,price_status,observation_request_id) VALUES(?,?,?,?,?,?,?,?,'pending',?,?,?,?,?,?,?,?)`, call.ID, call.Day, call.Timezone, role, model, session, request, call.Started, call.Currency, string(price), call.AgentKind, call.KeyID, call.SourceID, call.RouteID, call.PriceStatus, observationID)
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
		_, err := tx.Exec(`UPDATE gateway_calls SET state=?,finished_ms=?,input_tokens=?,output_tokens=?,cache_read_tokens=?,cost_nano=?,http_status=?,error_code=?,upstream_http_status=?,upstream_request_id=? WHERE id=? AND state='pending'`, state, l.now().UnixMilli(), input, output, cached, cost, status, code, call.upstreamStatus, call.upstreamRequestID, call.ID)
		return err
	})
}

func (l *Ledger) Reconcile(id string, amount float64, reason string) error {
	if !ValidAmount(amount) || len(reason) == 0 || len(reason) > 500 {
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
