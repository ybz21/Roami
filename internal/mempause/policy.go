// Package mempause chooses reversible pauses before memory exhaustion.
package mempause

const WarnPercent = 60
const PausePercent = 80

type Host struct {
	Total, Available int64
	Pressure         float64
}
type Sample struct {
	Name           string
	Current, Limit int64
	Paused         bool
	Grace          bool
	PressurePaused bool
}

func Warning(s Sample) bool {
	return s.Limit > 0 && float64(s.Current)/float64(s.Limit) >= float64(WarnPercent)/100
}

func Pressure(h Host) bool {
	return h.Total > 0 && h.Available > 0 &&
		(float64(h.Available)/float64(h.Total) < .12 || h.Pressure >= 10)
}

// Plan pauses at most one pressure contributor per sample, plus individual limits.
// Paused sessions require an explicit resume even if host memory recovers.
func Plan(h Host, samples []Sample) map[string]string {
	out := map[string]string{}
	var largest *Sample
	pressureHandled := false
	for i := range samples {
		s := &samples[i]
		pressureHandled = pressureHandled || (s.Paused && s.PressurePaused)
		if s.Current >= 512<<20 && (largest == nil || s.Current > largest.Current) {
			largest = s
		}
		if s.Paused || s.Grace {
			continue
		}
		if s.Limit > 0 && float64(s.Current)/float64(s.Limit) >= float64(PausePercent)/100 {
			out[s.Name] = "limit"
		}
	}
	if Pressure(h) && !pressureHandled && largest != nil && !largest.Paused && !largest.Grace {
		out[largest.Name] = "pressure"
	}
	return out
}
