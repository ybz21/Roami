package okr

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func TestMemoryAppendRetainsExactPriorBytesAndCAS(t *testing.T) {
	s, dir := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	original := "# Team\nVerified publication receipt.\n\n\n"
	w, err = s.WriteMemory("project", original, w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	hash := w.ProjectFiles.TeamMemorySha256
	var group sync.WaitGroup
	results := make(chan error, 2)
	for _, addition := range []string{"New observation A", "New observation B"} {
		group.Add(1)
		go func(text string) { defer group.Done(); _, e := s.AppendMemory("project", text, hash); results <- e }(addition)
	}
	group.Wait()
	close(results)
	success, conflicts := 0, 0
	for e := range results {
		if e == nil {
			success++
		} else if errors.Is(e, ErrConflict) {
			conflicts++
		} else {
			t.Fatal(e)
		}
	}
	if success != 1 || conflicts != 1 {
		t.Fatal(success, conflicts)
	}
	w, err = s.Get("project")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(w.ProjectFiles.TeamMemory, original) || w.Revision != 1 {
		t.Fatal(w.ProjectFiles, w.Revision)
	}
	previous, err := os.ReadFile(filepath.Join(dir, bundleRoot, "memory/history", hash+".md"))
	if err != nil || string(previous) != original {
		t.Fatalf("prior bytes lost: %q %v", previous, err)
	}
	// Even an erroneous full replacement can be reversed through the existing CAS operation.
	current := w.ProjectFiles.TeamMemory
	w, err = s.WriteMemory("project", "probe", w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	prior, err := os.ReadFile(filepath.Join(dir, bundleRoot, "memory/history", hashText([]byte(current))+".md"))
	if err != nil || string(prior) != current {
		t.Fatal(err, string(prior))
	}
	w, err = s.WriteMemory("project", string(prior), w.ProjectFiles.TeamMemorySha256)
	if err != nil || w.ProjectFiles.TeamMemory != current {
		t.Fatal(err, w)
	}
}

func TestMemoryHistoryFailureAndOversizedAppendPreserveCurrent(t *testing.T) {
	s, dir := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	w, err = s.WriteMemory("project", "Existing", w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	hash := w.ProjectFiles.TeamMemorySha256
	if _, err = s.AppendMemory("project", strings.Repeat("x", maxMemory), hash); !errors.Is(err, ErrInvalid) {
		t.Fatal(err)
	}
	root := filepath.Join(dir, bundleRoot, "memory/history")
	if err = os.RemoveAll(root); err != nil {
		t.Fatal(err)
	}
	outside := t.TempDir()
	if err = os.Symlink(outside, root); err != nil {
		t.Fatal(err)
	}
	if _, err = s.WriteMemory("project", "probe", hash); err == nil {
		t.Fatal("unsafe history allowed replacement")
	}
	b, err := os.ReadFile(filepath.Join(dir, bundleRoot, "memory/team.md"))
	if err != nil || string(b) != "Existing" {
		t.Fatal(string(b), err)
	}
	entries, err := os.ReadDir(outside)
	if err != nil || len(entries) != 0 {
		t.Fatal(entries, err)
	}
}
