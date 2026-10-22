package browsertabs

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"testing"
)

func TestCapacityDefaultsMigrationAndValidation(t *testing.T) {
	var policies Policies
	if err := json.Unmarshal([]byte(`{"agent":{"sleepAfterSeconds":0},"human":{"closeAfterSeconds":60}}`), &policies); err != nil {
		t.Fatal(err)
	}
	if policies.Agent.MaxTabs != 20 || policies.Agent.SleepAfterSeconds != 0 || policies.Human.MaxTabs != 0 {
		t.Fatal("older settings lost defaults or explicit zero", policies)
	}
	root := t.TempDir()
	for _, limit := range []int{0, 8, 50, 1000, -1, 1001} {
		policies.Agent.MaxTabs = limit
		policies.Human.CloseAfterSeconds = 0
		valid := limit >= 0 && limit <= 1000
		if policies.Valid() != valid {
			t.Fatalf("capacity %d validation", limit)
		}
		data, _ := json.Marshal(map[string]Policies{"tabPolicies": policies})
		if err := os.WriteFile(filepath.Join(root, "browser-config.json"), data, 0600); err != nil {
			t.Fatal(err)
		}
		got := ReadPolicies(root)
		if valid && got.Agent.MaxTabs != limit || !valid && got.Agent.MaxTabs != 20 {
			t.Fatal("catalog read disagrees with saved configuration", got)
		}
	}
}

func TestOriginPersistenceProtectionAndStaleMaintenance(t *testing.T) {
	root := t.TempDir()
	apply := func(e Event) Result {
		t.Helper()
		e.BrowserID = "browser"
		r, err := Apply(root, e)
		if err != nil {
			t.Fatal(err)
		}
		return r
	}
	r := apply(Event{Action: "sync", Targets: []string{"old", "human"}})
	if r.Entries["old"].Origin != "agent" || r.Policies.Human.CloseAfterSeconds != 0 {
		t.Fatal(r)
	}
	apply(Event{Action: "create", TargetID: "human", Origin: "human"})
	r = apply(Event{Action: "sync", Targets: []string{"old", "human"}})
	if r.Entries["human"].Origin != "human" || r.Entries["human"].CreatedBy != "human" {
		t.Fatal("lost human origin")
	}
	apply(Event{Action: "update", TargetID: "old", Origin: "human"})
	r = apply(Event{Action: "update", TargetID: "old", Origin: "agent"})
	if r.Entries["old"].CreatedBy != "agent" {
		t.Fatal("moving group rewrote original creator")
	}
	pinned := true
	apply(Event{Action: "update", TargetID: "old", Pinned: &pinned})
	if _, err := Apply(root, Event{Action: "maintain", BrowserID: "browser", TargetID: "old", Origin: "agent", Token: "close"}); err != ErrBusy {
		t.Fatal("pinned page was reserved", err)
	}
	pinned = false
	apply(Event{Action: "update", TargetID: "old", Pinned: &pinned})
	stamp := int64(1)
	if _, err := Apply(root, Event{Action: "maintain", BrowserID: "browser", TargetID: "old", Origin: "agent", Token: "close", LastUsedAt: &stamp}); err != ErrBusy {
		t.Fatal("stale idle snapshot accepted", err)
	}
	apply(Event{Action: "maintain", TargetID: "old", Origin: "agent", Token: "sleep"})
	if _, err := Apply(root, Event{Action: "update", BrowserID: "browser", TargetID: "old", Origin: "human"}); err != ErrBusy {
		t.Fatal("group change raced maintenance", err)
	}
	r = apply(Event{Action: "finish", TargetID: "old", Token: "sleep", Known: true, Sleeping: true})
	if !r.Entries["old"].Sleeping || len(r.Entries["old"].Busy) != 0 {
		t.Fatal(r)
	}
	apply(Event{Action: "start", TargetID: "old", Token: "action"})
	apply(Event{Action: "finish", TargetID: "old", Token: "action", Known: false})
	if _, err := Apply(root, Event{Action: "maintain", BrowserID: "browser", TargetID: "old", Origin: "agent", Token: "close"}); err != ErrBusy {
		t.Fatal("unknown action lost protection", err)
	}
	stat, _ := os.Stat(filepath.Join(root, "browser-tabs.json"))
	if stat.Mode().Perm() != 0600 {
		t.Fatal(stat.Mode())
	}
}

func TestConcurrentCatalogWritersPreserveEveryTab(t *testing.T) {
	root := t.TempDir()
	var group sync.WaitGroup
	for _, id := range []string{"one", "two", "three", "four"} {
		group.Add(1)
		go func(id string) {
			defer group.Done()
			if _, err := Apply(root, Event{Action: "create", BrowserID: "b", TargetID: id, Origin: "human"}); err != nil {
				t.Error(err)
			}
		}(id)
	}
	group.Wait()
	r, err := Apply(root, Event{Action: "sync", BrowserID: "b", Targets: []string{"one", "two", "three", "four"}})
	if err != nil || len(r.Entries) != 4 {
		t.Fatal(r, err)
	}
}
