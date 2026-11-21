package modelplugins

import (
	"cmp"
	"context"
	"slices"
	"strings"
	"time"
)

type AccountCall struct {
	Time   int64    `json:"t"`
	Model  string   `json:"model"`
	Input  int64    `json:"in"`
	Output int64    `json:"out"`
	Cost   *float64 `json:"cost"`
}

type reportedAccountCall struct {
	AccountCall
	ID string `json:"rid"`
}

func (m *Manager) RecentAccountCalls(ctx context.Context, source Source, now time.Time) ([]AccountCall, error) {
	worker, err := m.getWorker(ctx, source)
	if err != nil {
		return nil, err
	}
	since := now.Add(-24 * time.Hour).UnixMilli()
	var result struct {
		Calls []reportedAccountCall `json:"calls"`
	}
	err = worker.host.Call(ctx, "calls", map[string]any{"provider": source.ProviderID, "account": source.ProviderID, "since": since}, &result)
	if err != nil {
		return nil, err
	}
	slices.SortStableFunc(result.Calls, func(a, b reportedAccountCall) int { return cmp.Compare(b.Time, a.Time) })
	items := make([]AccountCall, 0, min(20, len(result.Calls)))
	seen := make(map[string]bool, cap(items))
	for _, call := range result.Calls {
		if call.Time < since || call.Time > now.UnixMilli() || call.ID == "" || seen[call.ID] {
			continue
		}
		seen[call.ID] = true
		call.Model = strings.ToValidUTF8(call.Model[:min(len(call.Model), 256)], "")
		items = append(items, call.AccountCall)
		if len(items) == 20 {
			break
		}
	}
	return items, nil
}
