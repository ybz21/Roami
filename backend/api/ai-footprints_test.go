package api

import (
	"bytes"
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/ttmux"
)

func TestAIFootprintsPersistCountsOnly(t *testing.T) {
	dir := t.TempDir()
	store := NewAIFootprintStore(dir)
	store.Record("dialogue", 2)
	store.Record("task", 1)
	store.Record("unknown", 10)
	events, failed := NewAIFootprintStore(dir).Snapshot()
	if failed || len(events) != 2 || events[0].Dialogues != 2 || events[1].Tasks != 1 {
		t.Fatalf("unexpected persisted counts: %+v, failed=%v", events, failed)
	}
	var fields map[string]any
	raw, err := os.ReadFile(filepath.Join(dir, "ai-footprints.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(bytes.Split(raw, []byte("\n"))[0], &fields); err != nil {
		t.Fatal(err)
	}
	if len(fields) != 3 {
		t.Fatalf("unexpected stored fields: %v", fields)
	}
}

func TestAIFootprintsCountSuccessfulSubmissions(t *testing.T) {
	for _, tc := range []struct {
		name, script, body, kind string
		want, status             int
	}{
		{"dialogue", "exit 0", `{"sess":"test","msg":"hello","activity":"dialogue"}`, "dialogue", 1, 200},
		{"task", "exit 0", `{"sess":"test","msg":"launch","activity":"task"}`, "task", 1, 200},
		{"shell", "exit 0", `{"sess":"test","msg":"ls"}`, "", 0, 200},
		{"paste failed", "exit 1", `{"sess":"test","msg":"hello","activity":"dialogue"}`, "", 0, 500},
		{"enter failed", `case "$*" in *Enter*) exit 1;; *) exit 0;; esac`, `{"sess":"test","msg":"hello","activity":"dialogue"}`, "", 0, 500},
		{"invalid kind", "exit 0", `{"sess":"test","msg":"hello","activity":"invalid"}`, "", 0, 400},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			bin := filepath.Join(dir, "ttmux")
			if err := os.WriteFile(bin, []byte("#!/bin/sh\n"+tc.script+"\n"), 0o755); err != nil {
				t.Fatal(err)
			}
			a := &API{TT: ttmux.New(bin), Footprints: NewAIFootprintStore(dir)}
			recorder := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(recorder)
			c.Request = httptest.NewRequest("POST", "/tasks/_/send", bytes.NewBufferString(tc.body))
			a.Send(c)
			events, failed := a.Footprints.Snapshot()
			if recorder.Code != tc.status || failed || len(events) != tc.want {
				t.Fatalf("status=%d events=%+v failed=%v", recorder.Code, events, failed)
			}
			if len(events) > 0 && ((tc.kind == "dialogue" && events[0].Dialogues != 1) || (tc.kind == "task" && events[0].Tasks != 1)) {
				t.Fatalf("wrong kind: %+v", events[0])
			}
		})
	}
}

func TestAIFootprintsExposePersistenceFailure(t *testing.T) {
	store := NewAIFootprintStore(t.TempDir())
	store.file = filepath.Join(t.TempDir(), "missing", "counts")
	store.Record("task", 1)
	events, failed := store.Snapshot()
	if !failed || len(events) != 0 {
		t.Fatalf("events=%+v failed=%v", events, failed)
	}
}

func TestAIFootprintsCountEachSpawnedAITask(t *testing.T) {
	dir := t.TempDir()
	bin := filepath.Join(dir, "ttmux")
	if err := os.WriteFile(bin, []byte("#!/bin/sh\nexit 0\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	a := &API{TT: ttmux.New(bin), Footprints: NewAIFootprintStore(dir)}
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	c.Request = httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"group":"test","type":"agent","tasks":[{"name":"a","task":"one"},{"name":"b","task":"two"}]}`))
	a.Spawn(c)
	events, failed := a.Footprints.Snapshot()
	if recorder.Code != 200 || failed || len(events) != 1 || events[0].Tasks != 2 {
		t.Fatalf("status=%d events=%+v", recorder.Code, events)
	}
}
