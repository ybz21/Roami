package agent

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestResolveBinary(t *testing.T) {
	for _, tc := range []struct {
		name     string
		pathMode os.FileMode
		homeMode os.FileMode
		wantPath bool
		missing  bool
	}{
		{name: "native install", homeMode: 0700},
		{name: "PATH takes priority", pathMode: 0700, homeMode: 0700, wantPath: true},
		{name: "non-executable PATH entry", pathMode: 0600, homeMode: 0700},
		{name: "non-executable native install", homeMode: 0600, missing: true},
		{name: "not installed", missing: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			home, pathDir := t.TempDir(), t.TempDir()
			t.Setenv("HOME", home)
			t.Setenv("PATH", pathDir)
			native := filepath.Join(home, ".opencode", "bin", "opencode")
			for path, mode := range map[string]os.FileMode{native: tc.homeMode, filepath.Join(pathDir, "opencode"): tc.pathMode} {
				if mode == 0 {
					continue
				}
				if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, []byte("#!/bin/sh\nexit 99\n"), mode); err != nil {
					t.Fatal(err)
				}
			}
			got, err := ResolveBinary("opencode")
			if tc.missing {
				if got != "" || err == nil {
					t.Fatalf("expected missing binary, got %q, %v", got, err)
				}
				return
			}
			want := native
			if tc.wantPath {
				want = filepath.Join(pathDir, "opencode")
			}
			if err != nil || got != want {
				t.Fatalf("got %q, %v; want %q", got, err, want)
			}
			if os.Getenv("PATH") != pathDir {
				t.Fatal("resolution changed process PATH")
			}
		})
	}
}

func TestResolveBinaryRejectsInvalidNativeEntries(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("PATH", t.TempDir())
	native := filepath.Join(home, ".opencode", "bin", "opencode")
	if err := os.MkdirAll(native, 0700); err != nil {
		t.Fatal(err)
	}
	if _, err := ResolveBinary("opencode"); err == nil {
		t.Fatal("accepted a directory")
	}
	if err := os.Remove(native); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(home, "missing"), native); err != nil {
		t.Fatal(err)
	}
	if _, err := ResolveBinary("opencode"); err == nil {
		t.Fatal("accepted a broken symlink")
	}
	t.Setenv("HOME", "")
	if _, err := ResolveBinary("opencode"); !errors.Is(err, exec.ErrNotFound) {
		t.Fatalf("missing home: %v", err)
	}
	if _, err := ResolveBinary("opencode;exit"); err == nil {
		t.Fatal("accepted an unregistered agent")
	}
}
