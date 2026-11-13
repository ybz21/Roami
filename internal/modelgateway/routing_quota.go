package modelgateway

import (
	"context"
	"github.com/ybz21/Roami/internal/modelplugins"
	"math"
	"strings"
	"sync"
	"time"
)

type creditExpiry struct {
	Amount float64
	At     time.Time
}
type routingQuota struct {
	Remaining, Capacity *float64
	Reset               time.Time
	Credits             []creditExpiry
	Known               bool
	Observed            time.Time
	ValidUntil          time.Time
}
type quotaCacheEntry struct {
	quota modelplugins.Quota
	valid bool
	next  time.Time
	ready chan struct{}
}
type quotaCache struct {
	mu      sync.Mutex
	entries map[string]*quotaCacheEntry
}

func (c *quotaCache) read(ctx context.Context, manager *modelplugins.Manager, source modelplugins.Source, account string) (modelplugins.Quota, bool) {
	key := source.ID + "/" + account
	now := time.Now()
	c.mu.Lock()
	if c.entries == nil {
		c.entries = map[string]*quotaCacheEntry{}
	}
	if entry := c.entries[key]; entry != nil {
		if entry.ready != nil {
			ready := entry.ready
			c.mu.Unlock()
			select {
			case <-ready:
				return c.read(ctx, manager, source, account)
			case <-ctx.Done():
				return modelplugins.Quota{}, false
			}
		}
		if now.Before(entry.next) && !quotaDeadlinePassed(entry.quota, now) {
			quota, valid := entry.quota, entry.valid && now.Sub(time.UnixMilli(entry.quota.ObservedAt)) < 2*time.Minute
			c.mu.Unlock()
			return quota, valid
		}
	}
	if len(c.entries) >= 4096 {
		for id, entry := range c.entries {
			if entry.ready == nil && now.After(entry.next.Add(5*time.Minute)) {
				delete(c.entries, id)
			}
		}
		if len(c.entries) >= 4096 {
			c.mu.Unlock()
			return modelplugins.Quota{}, false
		}
	}
	entry := &quotaCacheEntry{ready: make(chan struct{})}
	c.entries[key] = entry
	c.mu.Unlock()
	timeout, cancel := context.WithTimeout(ctx, 3*time.Second)
	quota, err := manager.AccountQuota(timeout, source, account)
	cancel()
	c.mu.Lock()
	entry.quota = quota
	entry.valid = err == nil && quota.Error == "" && quota.SignIn != "expired"
	delay := time.Minute
	if !entry.valid {
		delay = 30 * time.Second
	}
	entry.next = time.Now().Add(delay)
	close(entry.ready)
	entry.ready = nil
	valid := entry.valid
	c.mu.Unlock()
	return quota, valid
}
func quotaTimestamp(value string) time.Time {
	date, _ := time.Parse(time.RFC3339Nano, value)
	return date
}
func quotaDeadlinePassed(quota modelplugins.Quota, now time.Time) bool {
	observed := time.UnixMilli(quota.ObservedAt)
	deadlines := []time.Time{}
	if quota.Resets != nil {
		deadlines = append(deadlines, quotaTimestamp(quota.Resets.Until))
		for _, reset := range quota.Resets.Each {
			deadlines = append(deadlines, quotaTimestamp(reset.Until))
		}
	}
	for _, window := range quota.Windows {
		deadlines = append(deadlines, quotaTimestamp(window.ResetsAt), quotaTimestamp(window.RunsOutAt))
		if window.ResetSeconds > 0 {
			deadlines = append(deadlines, observed.Add(time.Duration(window.ResetSeconds)*time.Second))
		}
	}
	for _, at := range deadlines {
		if !at.IsZero() && observed.Before(at) && !now.Before(at) {
			return true
		}
	}
	return false
}
func quotaForModel(quota modelplugins.Quota, model string, now time.Time) routingQuota {
	observed := time.UnixMilli(quota.ObservedAt)
	result := routingQuota{Observed: observed, ValidUntil: observed.Add(2 * time.Minute)}
	if quota.ObservedAt == 0 || now.After(result.ValidUntil) || quota.Error != "" || quota.SignIn == "expired" {
		return result
	}
	var weekly, fiveHour, other *routingQuota
	for _, window := range quota.Windows {
		if window.Model != "" && window.Model != model || len(window.Models) > 0 && !containsField(window.Models, model) || containsField(window.NotModels, model) {
			continue
		}
		expiry := quotaTimestamp(window.RunsOutAt)
		if window.RunsOut > 0 && expiry.After(now) {
			result.Credits = append(result.Credits, creditExpiry{window.RunsOut, expiry})
		}
		if window.Aside {
			continue
		}
		remaining, capacity := window.Balance, window.Limit
		if remaining == nil && window.Used != nil {
			limit := capacity
			if limit <= 0 {
				limit = 100
			}
			left := math.Max(0, limit*(100-*window.Used)/100)
			remaining = &left
			capacity = limit
		}
		if remaining == nil && window.Limit > 0 {
			left := math.Max(0, window.Limit-window.Amount)
			remaining = &left
		}
		if remaining != nil && (math.IsNaN(*remaining) || math.IsInf(*remaining, 0) || *remaining < 0) {
			continue
		}
		reset := quotaTimestamp(window.ResetsAt)
		if reset.IsZero() && window.ResetSeconds > 0 {
			reset = observed.Add(time.Duration(window.ResetSeconds) * time.Second)
		}
		item := routingQuota{Remaining: remaining, Known: remaining != nil, Reset: reset, Observed: observed, ValidUntil: result.ValidUntil}
		if capacity > 0 {
			item.Capacity = &capacity
		}

		name := strings.ToLower(window.Name)
		if window.Span >= 6*86400 && window.Span <= 8*86400 || strings.Contains(name, "week") || strings.Contains(name, "周") {
			copy := item
			weekly = &copy
		} else if window.Span >= 4*3600 && window.Span <= 6*3600 || strings.Contains(name, "5h") || strings.Contains(name, "five") || strings.Contains(name, "5 小时") {
			copy := item
			fiveHour = &copy
		} else if item.Known {
			copy := item
			if other == nil || *copy.Remaining < *other.Remaining {
				other = &copy
			}
		}
	}
	credits := result.Credits
	if weekly != nil {
		result = *weekly
	} else if fiveHour != nil {
		result = *fiveHour
	} else if other != nil {
		result = *other
	}
	result.Credits = credits
	if result.Reset.IsZero() && quota.Resets != nil {
		var weeklyReset, fiveReset time.Time
		for _, reset := range quota.Resets.Each {
			if reset.Window == "weekly" {
				weeklyReset = quotaTimestamp(reset.Until)
			} else if reset.Window == "fiveHour" {
				fiveReset = quotaTimestamp(reset.Until)
			}
		}
		if !weeklyReset.IsZero() {
			result.Reset = weeklyReset
		} else if !fiveReset.IsZero() {
			result.Reset = fiveReset
		} else {
			result.Reset = quotaTimestamp(quota.Resets.Until)
		}
	}
	if !result.Reset.IsZero() && !result.Reset.After(now) {
		result.Known = false
		result.Remaining = nil
	}

	// A known depleted secondary window still blocks a usable weekly allowance.
	for _, window := range quota.Windows {
		if window.Aside || window.Model != "" && window.Model != model || len(window.Models) > 0 && !containsField(window.Models, model) || containsField(window.NotModels, model) {
			continue
		}
		if window.Balance != nil && *window.Balance <= 0 || window.Used != nil && *window.Used >= 100 {
			zero := float64(0)
			result.Remaining = &zero
			result.Known = true
		}
	}
	return result
}
