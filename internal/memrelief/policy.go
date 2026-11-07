// Package memrelief schedules bounded recovery before memory pauses.
package memrelief

import "time"

const ReclaimCooldown = time.Minute
const CompactCooldown = 10 * time.Minute

type State struct {
	ReclaimAt     int64  `json:"reclaimAt,omitempty"`
	ReclaimStatus string `json:"reclaimStatus,omitempty"`
	Reclaimed     int64  `json:"reclaimed,omitempty"`
	SwapDelta     int64  `json:"swapDelta,omitempty"`
	CompactAt     int64  `json:"compactAt,omitempty"`
	CompactStatus string `json:"compactStatus,omitempty"`
}

type Sample struct {
	Name           string
	Current, Limit int64
	Paused, Grace  bool
	State          State
}

func Warning(s Sample) bool { return s.Limit > 0 && float64(s.Current)/float64(s.Limit) >= .60 }

// One target per observation bounds latency regardless of the session count.
func Target(samples []Sample, pressure bool, now time.Time) string {
	var best *Sample
	for i := range samples {
		s := &samples[i]
		if s.Paused || s.Grace || s.Current < 128<<20 || (!Warning(*s) && !(pressure && s.Current >= 512<<20)) || now.Unix()-s.State.ReclaimAt < int64(ReclaimCooldown/time.Second) {
			continue
		}
		if best == nil || s.Current > best.Current {
			best = s
		}
	}
	if best == nil {
		return ""
	}
	return best.Name
}

func Bytes(current, swapFree int64) int64 {
	n := current / 8
	if n > 128<<20 {
		n = 128 << 20
	}
	if n > swapFree/2 {
		n = swapFree / 2
	}
	if n < 16<<20 {
		return 0
	}
	return n
}

// Only an empty input at the cursor in a supported foreground TUI is eligible.
func EmptyPrompt(kind, screen string, cursorY int) bool {
	if kind != "codex" && kind != "claude" {
		return false
	}
	return emptyPrompt(kind, screen, cursorY)
}
