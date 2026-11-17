package modelplugins

import (
	"context"
	"time"
)

type QuotaWindow struct {
	Name         string   `json:"name"`
	Used         *float64 `json:"used"`
	ResetsAt     string   `json:"resetsAt"`
	ResetSeconds int64    `json:"resetSecs"`
	Amount       float64  `json:"amount"`
	Limit        float64  `json:"limit"`
	Unit         string   `json:"unit"`
	Span         int64    `json:"span"`
	Model        string   `json:"model"`
	Models       []string `json:"models"`
	NotModels    []string `json:"notModels"`
	Aside        bool     `json:"aside"`
	RunsOutAt    string   `json:"runsOutAt"`
	RunsOut      float64  `json:"runsOut"`
	Balance      *float64 `json:"balance"`
}
type QuotaResets struct {
	Until string `json:"until"`
	Each  []struct {
		Until  string `json:"until"`
		Window string `json:"window"`
	} `json:"each"`
}
type Quota struct {
	Resets     *QuotaResets  `json:"resets"`
	Error      string        `json:"error"`
	SignIn     string        `json:"signIn"`
	Windows    []QuotaWindow `json:"windows"`
	ObservedAt int64         `json:"observedAt"`
}

func (m *Manager) AccountQuota(ctx context.Context, source Source, account string) (Quota, error) {
	worker, err := m.getWorker(ctx, source)
	if err != nil {
		return Quota{}, err
	}
	var quota Quota
	err = worker.host.Call(ctx, "usage", map[string]any{"provider": source.ProviderID, "account": account}, &quota)
	quota.ObservedAt = time.Now().UnixMilli()
	return quota, err
}
