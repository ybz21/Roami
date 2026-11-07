package mempause

import "testing"

func TestWarnBeforePauseAndKeepPausedUntilUserResumes(t *testing.T) {
	s := Sample{Name: "okr", Current: 6 << 30, Limit: 10 << 30}
	if !Warning(s) || len(Plan(Host{}, []Sample{s})) != 0 {
		t.Fatal("60% should warn without stopping work")
	}
	s.Current = 8 << 30
	if Plan(Host{}, []Sample{s})[s.Name] != "limit" {
		t.Fatal("80% should pause before the hard cap")
	}
	s.Paused = true
	if len(Plan(Host{Total: 32 << 30, Available: 20 << 30}, []Sample{s})) != 0 {
		t.Fatal("paused work must not be automatically resumed")
	}
	s.Paused, s.Grace = false, true
	if len(Plan(Host{}, []Sample{s})) != 0 {
		t.Fatal("explicit resume must have a grace period")
	}
}

func TestHostPressureActsBelowPerSessionLimit(t *testing.T) {
	samples := []Sample{{Name: "large", Current: 9 << 30, Limit: 13 << 30}, {Name: "small", Current: 1 << 30}}
	h := Host{Total: 32 << 30, Available: 2 << 30}
	p := Plan(h, samples)
	if len(p) != 1 || p["large"] != "pressure" {
		t.Fatalf("must pause only the largest contributor: %v", p)
	}
	samples[0].Paused, samples[0].PressurePaused = true, true
	if len(Plan(h, samples)) != 0 {
		t.Fatal("successive polls must not freeze every remaining session")
	}
	samples[0].Paused, samples[0].PressurePaused, samples[0].Grace = false, false, true
	if len(Plan(h, samples)) != 0 {
		t.Fatal("resume grace must not redirect pressure actions to a smaller session")
	}
	h.Available, h.Pressure = 10<<30, 12
	samples[0].Grace = false
	if Plan(h, samples)["large"] != "pressure" {
		t.Fatal("PSI must catch pressure even with reclaimable available memory")
	}
}

func TestUnknownHostAndTinySessionsAreNotPressureTargets(t *testing.T) {
	for _, h := range []Host{{}, {Total: 32 << 30}, {Total: 32 << 30, Available: 12 << 30}} {
		if len(Plan(h, []Sample{{Name: "tiny", Current: 100 << 20}})) != 0 {
			t.Fatal("unsafe pressure target")
		}
	}
}
