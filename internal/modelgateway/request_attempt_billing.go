package modelgateway

import (
	"context"
	"database/sql"
)

type requestAttemptDetail struct {
	MonitorRecord
	Billing requestAttemptBilling `json:"billing"`
}

type requestAttemptBilling struct {
	State             string  `json:"state"`
	Currency          string  `json:"currency,omitempty"`
	Cost              *string `json:"cost,omitempty"`
	UpstreamRequestID string  `json:"upstreamRequestId,omitempty"`
}

type requestAttemptLedgerEntry struct {
	sourceID, routeID, model string
	billing                  requestAttemptBilling
}

func (l *Ledger) readRequestAttemptBilling(ctx context.Context, requestID string) (map[string]requestAttemptLedgerEntry, error) {
	// Ledger request_id belongs to the caller; only the server-generated observation ID proves ownership.
	rows, err := l.db.QueryContext(ctx, `SELECT id,source_id,route_id,model,state,currency,cost_nano,upstream_request_id
FROM gateway_calls WHERE observation_request_id=? AND observation_request_id!=''`, requestID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	entries := make(map[string]requestAttemptLedgerEntry)
	for rows.Next() {
		var id, state, currency string
		var entry requestAttemptLedgerEntry
		var amount sql.NullInt64
		if err := rows.Scan(&id, &entry.sourceID, &entry.routeID, &entry.model, &state, &currency, &amount, &entry.billing.UpstreamRequestID); err != nil {
			return nil, err
		}
		switch {
		case state == "pending":
			entry.billing.State = "pending"
		case amount.Valid:
			value := money(amount.Int64)
			entry.billing.State, entry.billing.Cost, entry.billing.Currency = "settled", &value, currency
		default:
			entry.billing.State = "unknown"
		}
		entries[id] = entry
	}
	return entries, rows.Err()
}

func (h *Handler) requestAttemptsWithBilling(ctx context.Context, request MonitorRecord, attempts []MonitorRecord) []requestAttemptDetail {
	result := make([]requestAttemptDetail, len(attempts))
	var entries map[string]requestAttemptLedgerEntry
	var err error
	if h.Ledger != nil {
		for _, attempt := range attempts {
			if attempt.CallID != "" {
				entries, err = h.Ledger.readRequestAttemptBilling(ctx, request.RequestID)
				break
			}
		}
	}
	for i, attempt := range attempts {
		entry, found := entries[attempt.CallID]
		billing := requestAttemptBilling{State: "unrecorded"}
		switch {
		case attempt.CallID == "":
		case h.Ledger == nil || err != nil:
			billing.State = "unavailable"
		case !found || attempt.RequestID != request.RequestID || attempt.RouteID != request.RouteID ||
			entry.sourceID != attempt.SourceID || entry.routeID != attempt.RouteID || entry.model != attempt.Model:
			billing.State = "missing"
		default:
			billing = entry.billing
		}
		result[i] = requestAttemptDetail{MonitorRecord: attempt, Billing: billing}
	}
	return result
}
