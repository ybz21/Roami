package modelplugins

import (
	"context"
	"errors"
	"time"
)

type CheckInResult struct {
	Outcome string  `json:"outcome"`
	Credit  float64 `json:"credit"`
	Streak  int     `json:"streak"`
	Until   string  `json:"until,omitempty"`
}

func (m *Manager) CheckIn(ctx context.Context, source Source) (CheckInResult, error) {
	worker, err := m.getWorker(ctx, source)
	if err != nil {
		return CheckInResult{}, err
	}
	if !worker.checkInMu.TryLock() {
		return CheckInResult{}, errors.New("MODEL_PLUGIN_BUSY")
	}
	defer worker.checkInMu.Unlock()
	if err = ctx.Err(); err != nil {
		return CheckInResult{}, err
	}
	ctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 25*time.Second)
	defer cancel()
	var result CheckInResult
	err = worker.host.Call(ctx, "checkin", map[string]any{"provider": source.ProviderID, "account": source.ProviderID}, &result)
	return result, err
}
