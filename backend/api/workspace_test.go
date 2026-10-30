package api

import (
	"os"
	"reflect"
	"sync"
	"testing"
)

func TestWorkspaceConcurrentClientsAndRestart(t *testing.T) {
	dir := t.TempDir()
	store := NewWorkspaceStore(dir)
	var wg sync.WaitGroup
	for _, id := range []string{"desktop", "phone", "tablet"} {
		wg.Add(1)
		go func(id string) {
			defer wg.Done()
			if _, err := store.update(nil, []WorkspaceChange{{Add: []string{id}, Active: &id}}); err != nil {
				t.Error(err)
			}
		}(id)
	}
	wg.Wait()
	state, err := NewWorkspaceStore(dir).read()
	if err != nil || len(state.Terms) != 3 || state.Revision != 3 {
		t.Fatalf("lost concurrent edit: %+v, %v", state, err)
	}
	// A stale client's reorder and close must retain tabs opened elsewhere.
	state, err = store.update(nil, []WorkspaceChange{{Order: []string{"phone"}, Remove: []string{"desktop"}}})
	if err != nil || len(state.Terms) != 2 || state.Terms[0] != "phone" {
		t.Fatalf("stale edit replaced tabs: %+v, %v", state, err)
	}
}

func TestWorkspaceImportsOnlyOnceAndKeepsExplicitEmpty(t *testing.T) {
	store := NewWorkspaceStore(t.TempDir())
	seed := &WorkspaceState{Terms: []string{"old", "old"}, Active: "missing"}
	state, err := store.update(seed, nil)
	if err != nil || !reflect.DeepEqual(state.Terms, []string{"old"}) || state.Active != "old" {
		t.Fatalf("bad import: %+v, %v", state, err)
	}
	state, err = store.update(nil, []WorkspaceChange{{Remove: []string{"old"}}})
	if err != nil || len(state.Terms) != 0 || state.Active != "" {
		t.Fatalf("bad close: %+v, %v", state, err)
	}
	state, err = store.update(seed, nil)
	if err != nil || len(state.Terms) != 0 {
		t.Fatalf("old link revived closed tabs: %+v, %v", state, err)
	}
}

func TestWorkspaceFileEditsAndReadFailure(t *testing.T) {
	store := NewWorkspaceStore(t.TempDir())
	path := "/repo/readme.md"
	state, err := store.update(nil, []WorkspaceChange{{Files: []WorkspaceFile{{Path: path, Mode: "preview"}}, ActiveFile: &path}})
	if err != nil || state.ActiveFile != path {
		t.Fatalf("file not selected: %+v, %v", state, err)
	}
	state, err = store.update(nil, []WorkspaceChange{{RemoveFiles: []string{path}}})
	if err != nil || state.ActiveFile != "" || len(state.Files) != 0 {
		t.Fatalf("closed file still selected: %+v, %v", state, err)
	}
	if err := os.WriteFile(store.file, []byte("broken"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := store.update(nil, nil); err == nil {
		t.Fatal("corrupt state was silently overwritten")
	}
}
