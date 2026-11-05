package session

import (
	"encoding/json"
	"strings"
	"testing"

	sessmeta "github.com/ybz21/Roami/internal/sessionstore"
)

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
