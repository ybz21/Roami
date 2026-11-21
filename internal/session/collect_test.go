package session

import (
	"encoding/json"
	"strings"
	"testing"

	sessmeta "github.com/ybz21/Roami/internal/sessionstore"
)

func TestSessionListUsesMostRecentWindowOutput(t *testing.T) {
	sessions := parseSessionLines("work\t2\t100\t1\t150 200 \t$2\t活动会话\tpressure\t300\n"+
		"quiet\t1\t120\t0\t\t$3\n", nil)
	if len(sessions) != 2 {
		t.Fatalf("parsed sessions: %+v", sessions)
	}
	active, quiet := sessions[0], sessions[1]
	if active.LastActivity != "200" || active.TmuxID != "$2" || active.Label != "活动会话" || active.pauseReason != "pressure" || active.resumeUntil != 300 {
		t.Fatalf("parsed active session: %+v", active)
	}
	if quiet.LastActivity != "120" {
		t.Fatalf("activity without window time = %q, want 120", quiet.LastActivity)
	}
}

func TestFlatSessionListKeepsRecordedLineage(t *testing.T) {
	store := sessmeta.New(t.TempDir())
	// Reading the existing collection must not start another tmux scan.
	store.WithIDs(func() map[string]string { return nil })
	for _, row := range []sessmeta.Row{
		{Session: "child", Parent: "parent", CreatedBy: "fork"},
		{Session: "grandchild", Parent: "child", CreatedBy: "fork"},
		{Session: "orphan", Parent: "absent", CreatedBy: "fork"},
	} {
		if err := store.Put(row); err != nil {
			t.Fatal(err)
		}
	}
	store.WithIDs(func() map[string]string { t.Fatal("unexpected tmux observation"); return nil })
	sessions := attachLineage([]sessionInfo{{Name: "parent"}, {Name: "child"}, {Name: "grandchild"}, {Name: "orphan"}, {Name: "dormant", State: "dormant", Parent: "parent"}}, store)
	if sessions[1].Parent != "parent" || sessions[2].Parent != "child" || sessions[1].CreatedBy != "fork" {
		t.Fatalf("lost lineage: %+v", sessions)
	}
	if sessions[3].Parent != "" || sessions[4].Parent != "parent" {
		t.Fatalf("orphan/dormant lineage: %+v", sessions)
	}
	data, err := json.Marshal(sessions)
	if err != nil || !strings.Contains(string(data), `"parent":"parent"`) {
		t.Fatalf("flat JSON lineage: %s %v", data, err)
	}
	if store.Parent("orphan") != "absent" {
		t.Fatal("projection rewrote saved ancestry")
	}
}
