package agentruntime

import (
	metadb "github.com/ybz21/Roami/internal/storage"
	"os"
	"path/filepath"
	"testing"
)

func TestPathsBoundToCatalogInstance(t *testing.T) {
	home := t.TempDir()
	p, err := metadb.ResolvePaths(home, home)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = p.Ensure(); err != nil {
		t.Fatal(err)
	}
	runtime := t.TempDir()
	if err = os.Chmod(runtime, 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("XDG_RUNTIME_DIR", runtime)
	first, err := Resolve(home, home)
	if err != nil {
		t.Fatal(err)
	}
	other := t.TempDir()
	p2, err := metadb.ResolvePaths(other, other)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = p2.Ensure(); err != nil {
		t.Fatal(err)
	}
	second, err := Resolve(other, other)
	if err != nil {
		t.Fatal(err)
	}
	if first.Socket == second.Socket || first.InstanceID == second.InstanceID {
		t.Fatal("instances share runtime identity")
	}
	if first.Database != filepath.Join(p.Database, "agents", "runtime.db") {
		t.Fatal(first.Database)
	}
}
