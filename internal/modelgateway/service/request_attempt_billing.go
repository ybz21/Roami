package service

import (
	"context"

	"github.com/ybz21/Roami/internal/modelgateway/accounting"
	"github.com/ybz21/Roami/internal/modelgateway/monitor"
)

type requestAttemptDetail struct {
	monitor.Record
	Billing accounting.AttemptBilling `json:"billing"`
}

func (h *Handler) requestAttemptsWithBilling(ctx context.Context, request monitor.Record, attempts []monitor.Record) []requestAttemptDetail {
	result := make([]requestAttemptDetail, len(attempts))
	var entries map[string]accounting.AttemptLedgerEntry
	var err error
	if h.state != nil {
		for _, attempt := range attempts {
			if attempt.CallID != "" {
				entries, err = h.state.accounting.RequestAttempts(ctx, request.RequestID)
				break
			}
		}
	}
	for i, attempt := range attempts {
		entry, found := entries[attempt.CallID]
		billing := accounting.AttemptBilling{State: "unrecorded"}
		switch {
		case attempt.CallID == "":
		case h.state == nil || err != nil:
			billing.State = "unavailable"
		case !found || attempt.RequestID != request.RequestID || attempt.RouteID != request.RouteID ||
			entry.SourceID != attempt.SourceID || entry.RouteID != attempt.RouteID || entry.Model != attempt.Model:
			billing.State = "missing"
		default:
			billing = entry.Billing
		}
		result[i] = requestAttemptDetail{Record: attempt, Billing: billing}
	}
	return result
}
