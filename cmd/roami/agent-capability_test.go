package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestAgentCapabilityListsCategoriesAndRejectsRemovedSearch(t *testing.T) {
	if code := runAgentCapability([]string{"list", "--help"}); code != 0 {
		t.Fatalf("list help exit: %d", code)
	}
	if code := runAgentCapability([]string{"search", "--query", "browser"}); code != 2 {
		t.Fatalf("removed search entry remained callable: %d", code)
	}
}

func TestCapabilityContextRequiresPrivateRegularJSONFile(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "context.json")
	if err := os.WriteFile(path, []byte(`{"taskId":"own-task"}`), 0600); err != nil {
		t.Fatal(err)
	}
	value, err := readCapabilityContext(path)
	if err != nil || value["taskId"] != "own-task" {
		t.Fatalf("private context: %v %v", value, err)
	}
	link := filepath.Join(root, "link.json")
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	if _, err := readCapabilityContext(link); err == nil {
		t.Fatal("accepted a symlink")
	}
	if err := os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := readCapabilityContext(path); err == nil {
		t.Fatal("accepted a public context")
	}
	if _, err := readCapabilityContext(root); err == nil {
		t.Fatal("accepted a directory")
	}
}
