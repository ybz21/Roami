package session

import "github.com/ybz21/Roami/internal/memthrottle"

func filterPausedBrakes(brakes []memthrottle.Sample, sessions []sessionInfo) []memthrottle.Sample {
	paused := map[string]bool{}
	for _, s := range sessions {
		if s.Mem != nil && s.Mem.Paused {
			paused[s.Name] = true
		}
	}
	out := brakes[:0]
	for _, s := range brakes {
		if !paused[s.Session] {
			out = append(out, s)
		}
	}
	return out
}
