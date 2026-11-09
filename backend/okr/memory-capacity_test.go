package okr

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestFullMemoryCanCondenseAndAppendWithoutLosingHistory(t *testing.T) {
	s, project := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	prefix := "Active rule: preserve originals.\n"
	original := prefix + strings.Repeat("x", maxMemory-len(prefix)-1024)
	if len(original) >= maxMemory {
		t.Fatal("invalid fixture")
	}
	w, err = s.WriteMemory("project", original, w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	before := w.ProjectFiles.TeamMemorySha256
	addition := strings.Repeat("new verified fact. ", 100)
	_, err = s.AppendMemoryOnce("project", "daily-append", addition, before)
	var capacity *MemoryCapacityError
	if !errors.As(err, &capacity) || capacity.CurrentBytes != len(original) || capacity.RequestedBytes <= maxMemory || capacity.LimitBytes != maxMemory {
		t.Fatalf("wrong capacity error: %#v %v", capacity, err)
	}
	current, err := s.Get("project")
	if err != nil || current.ProjectFiles.TeamMemory != original {
		t.Fatal("failed append changed memory", err)
	}
	summary := "Active rule: preserve originals.\nHistorical dated records retained in memory/history/" + before + ".md"
	w, err = s.EditMemoryOnce("project", "daily-condense", before, []MemoryEdit{{original, summary}})
	if err != nil {
		t.Fatal(err)
	}
	history, err := os.ReadFile(filepath.Join(project, bundleRoot, "memory/history", before+".md"))
	if err != nil || string(history) != original {
		t.Fatal("archive lost original bytes", err)
	}
	w, err = s.AppendMemoryOnce("project", "daily-append", addition, w.ProjectFiles.TeamMemorySha256)
	if err != nil || w.ProjectFiles.TeamMemory != summary+"\n\n"+addition {
		t.Fatal("append did not recover", err)
	}
	if _, err := s.EditMemoryOnce("project", "stale", before, []MemoryEdit{{"Active rule", "Changed rule"}}); !errors.Is(err, ErrConflict) {
		t.Fatal("stale CAS accepted", err)
	}
}
