package sessmeta

import (
	"testing"
)

func TestShardedReconcileIsolatesBackendsAndDrainingHosts(t *testing.T) {
	s, _ := newTestStore(t, map[string]string{"tmux-1": "$1"})
	dir := t.TempDir()

	if err := s.Put(Row{Session: "tmux-1", Backend: "tmux", InitialCwd: dir}); err != nil {
		t.Fatal(err)
	}
	if err := s.Put(Row{Session: "nat-h1", Backend: "native", HostInstanceID: "h1", InitialCwd: dir}); err != nil {
		t.Fatal(err)
	}
	if err := s.Put(Row{Session: "nat-h2", Backend: "native", HostInstanceID: "h2", InitialCwd: dir}); err != nil {
		t.Fatal(err)
	}

	// tmux server gone must NOT kill native sessions on h1 or h2.
	s.ReconcileServerGone()
	if row, ok := s.Get("tmux-1"); !ok || row.Status != "dead" {
		t.Fatalf("tmux-1 should be dead, got %+v", row)
	}
	for _, id := range []string{"nat-h1", "nat-h2"} {
		if row, ok := s.Get(id); !ok || row.Status != "live" {
			t.Fatalf("%s must stay live when tmux server is gone, got %+v", id, row)
		}
	}

	// Reconciling native host h1 with empty alive set only marks h1's sessions dead, leaving h2 live.
	s.ReconcileHost("native", "h1", map[string]bool{})
	if row, ok := s.Get("nat-h1"); !ok || row.Status != "dead" {
		t.Fatalf("nat-h1 should be dead, got %+v", row)
	}
	if row, ok := s.Get("nat-h2"); !ok || row.Status != "live" {
		t.Fatalf("nat-h2 must stay live when reconciling h1, got %+v", row)
	}
}

func TestDormantAggregatesMultiHostRebootByBootID(t *testing.T) {
	s, _ := newTestStore(t, map[string]string{"tmux-1": "$1"})
	dir := t.TempDir()

	if err := s.Put(Row{Session: "tmux-1", Backend: "tmux", InitialCwd: dir}); err != nil {
		t.Fatal(err)
	}
	if err := s.Put(Row{Session: "nat-h1", Backend: "native", HostInstanceID: "h1", InitialCwd: dir}); err != nil {
		t.Fatal(err)
	}
	if err := s.Put(Row{Session: "nat-h2", Backend: "native", HostInstanceID: "h2", InitialCwd: dir}); err != nil {
		t.Fatal(err)
	}

	bootID := "boot-2026-11-23-01"
	s.ReconcileHostGone("tmux", "", bootID)
	s.ReconcileHostGone("native", "h1", bootID)
	s.ReconcileHostGone("native", "h2", bootID)

	dormant := s.Dormant()
	if len(dormant) != 3 {
		t.Fatalf("expected all 3 multi-host sessions in Dormant(), got %d: %+v", len(dormant), dormant)
	}
}
