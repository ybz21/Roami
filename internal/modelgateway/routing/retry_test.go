package routing

import (
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/modelplugins"
)

func TestFreeModelRetryNeedsEveryApplicableDepletedWindowReset(t *testing.T) {
	now := time.Date(2026, time.November, 21, 12, 0, 0, 0, time.UTC)
	soon, late := now.Add(time.Hour), now.Add(2*time.Hour)
	zero := float64(0)
	quota := modelplugins.Quota{ObservedAt: now.UnixMilli(), Windows: []modelplugins.QuotaWindow{
		{Name: "Weekly", Balance: &zero, ResetsAt: soon.Format(time.RFC3339)},
		{Name: "5h", Balance: &zero, ResetsAt: late.Format(time.RFC3339)},
		{Model: "other", Balance: &zero},
	}}
	if result := quotaForModel(quota, "fixture", now); !result.RetryAt.Equal(late) || !result.Reset.Equal(soon) {
		t.Fatalf("retry time must honor both windows without changing the existing primary reset: %+v", result)
	}
	quota.Windows[1].ResetsAt = ""
	if result := quotaForModel(quota, "fixture", now); !result.RetryAt.IsZero() {
		t.Fatalf("depleted window with unknown reset must not advertise retry: %+v", result)
	}
}
