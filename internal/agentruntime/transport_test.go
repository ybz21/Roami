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

func TestPathsDoNotDependOnInteractiveRuntimeDirectory(t *testing.T) {
	home := t.TempDir()
	p, err := metadb.ResolvePaths(home, home)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = p.Ensure(); err != nil {
		t.Fatal(err)
	}
	t.Setenv("XDG_RUNTIME_DIR", t.TempDir())
	first, err := Resolve(home, home)
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("XDG_RUNTIME_DIR", "")
	second, err := Resolve(home, home)
	if err != nil {
		t.Fatal(err)
	}
	if first.Socket != second.Socket {
		t.Fatal("service and CLI resolve different sockets")
	}
}

func TestLongHomeUsesSamePrivateShortSocket(t *testing.T) {
	home := t.TempDir()
	for range 5 {
		home = filepath.Join(home, "long-instance-directory")
	}
	p, err := metadb.ResolvePaths(home, home)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = p.Ensure(); err != nil {
		t.Fatal(err)
	}
	paths, err := Resolve(home, home)
	if err != nil {
		t.Fatal(err)
	}
	if len(paths.Socket) > 103 {
		t.Fatal(paths.Socket)
	}
	info, err := os.Lstat(filepath.Dir(paths.Socket))
	if err != nil || !info.IsDir() || info.Mode().Perm() != 0700 {
		t.Fatal(info, err)
	}
}
