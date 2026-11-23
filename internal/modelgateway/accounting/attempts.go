package accounting

import (
	"context"
	"database/sql"
)

type AttemptBilling struct {
	State             string  `json:"state"`
	Currency          string  `json:"currency,omitempty"`
	Cost              *string `json:"cost,omitempty"`
	UpstreamRequestID string  `json:"upstreamRequestId,omitempty"`
}

type AttemptLedgerEntry struct {
	SourceID, RouteID, Model string
	Billing                  AttemptBilling
}

func (l *Ledger) RequestAttempts(ctx context.Context, requestID string) (map[string]AttemptLedgerEntry, error) {
	// Ledger request_id belongs to the caller; only the server-generated observation ID proves ownership.
	rows, err := l.db.QueryContext(ctx, `SELECT id,source_id,route_id,model,state,currency,cost_nano,upstream_request_id
FROM gateway_calls WHERE observation_request_id=? AND observation_request_id!=''`, requestID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	entries := make(map[string]AttemptLedgerEntry)
	for rows.Next() {
		var id, state, currency string
		var entry AttemptLedgerEntry
		var amount sql.NullInt64
		if err := rows.Scan(&id, &entry.SourceID, &entry.RouteID, &entry.Model, &state, &currency, &amount, &entry.Billing.UpstreamRequestID); err != nil {
			return nil, err
		}
		switch {
		case state == "pending":
			entry.Billing.State = "pending"
		case amount.Valid:
			value := money(amount.Int64)
			entry.Billing.State, entry.Billing.Cost, entry.Billing.Currency = "settled", &value, currency
		default:
			entry.Billing.State = "unknown"
		}
		entries[id] = entry
	}
	return entries, rows.Err()
}
