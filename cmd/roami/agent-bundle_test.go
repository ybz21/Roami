package main

import (
	"archive/tar"
	"compress/gzip"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestBundleRejectsEscapingEntriesAndLinks(t *testing.T) {
	for _, header := range []*tar.Header{
		{Name: "../escaped", Typeflag: tar.TypeReg, Mode: 0755},
		{Name: "/escaped", Typeflag: tar.TypeReg, Mode: 0755},
		{Name: "runtime/python", Typeflag: tar.TypeSymlink, Linkname: "/tmp"},
		{Name: "runtime/.venv/payload", Typeflag: tar.TypeReg},
	} {
		t.Run(header.Name, func(t *testing.T) {
			root := t.TempDir()
			archive := filepath.Join(root, "bundle.tar.gz")
			file, err := os.Create(archive)
			if err != nil {
				t.Fatal(err)
			}
			compressed := gzip.NewWriter(file)
			writer := tar.NewWriter(compressed)
			if err := writer.WriteHeader(header); err != nil {
				t.Fatal(err)
			}
			writer.Close()
			compressed.Close()
			file.Close()
			destination := filepath.Join(root, "release")
			if err := installAgentBundle(archive, destination); err == nil {
				t.Fatal("unsafe archive accepted")
			}
			if _, err := os.Stat(destination); !os.IsNotExist(err) {
				t.Fatal("failed install left a partial release")
			}
		})
	}
}

func TestBundleActivationReplacesDirectorySymlinkAndPreservesPrevious(t *testing.T) {
	root := filepath.Join(t.TempDir(), "install with spaces")
	bindir := filepath.Join(root, "bin")
	if err := os.MkdirAll(bindir, 0755); err != nil {
		t.Fatal(err)
	}
	entry := filepath.Join(bindir, "roami")
	os.WriteFile(entry, []byte("old single binary"), 0755)
	var slots []string
	for _, name := range []string{"first", "second"} {
		slot := filepath.Join(root, "releases", name)
		os.MkdirAll(filepath.Join(slot, "bin"), 0755)
		os.WriteFile(filepath.Join(slot, "ready"), []byte("{}"), 0600)
		os.WriteFile(filepath.Join(slot, "bin", "roami"), []byte(name), 0755)
		if err := activateAgentBundle(slot, bindir); err != nil {
			t.Fatal(err)
		}
		content, err := os.ReadFile(entry)
		if err != nil || string(content) != name {
			t.Fatalf("entry %s: %s %v", name, content, err)
		}
		slots = append(slots, slot)
	}
	previous, err := os.Readlink(filepath.Join(root, "previous"))
	if err != nil || previous != slots[0] {
		t.Fatal(previous, err)
	}
	content, err := os.ReadFile(filepath.Join(root, "previous-binary"))
	if err != nil || !strings.Contains(string(content), "old single binary") {
		t.Fatal(string(content), err)
	}
	if err := activateAgentBundle(slots[0], bindir); err != nil {
		t.Fatal(err)
	}
}

func TestBundleActivationRestoresPointerIfEntryCannotBeReplaced(t *testing.T) {
	root := t.TempDir()
	slots := []string{filepath.Join(root, "releases", "old"), filepath.Join(root, "releases", "new")}
	for _, slot := range slots {
		os.MkdirAll(slot, 0700)
		os.WriteFile(filepath.Join(slot, "ready"), []byte("{}"), 0600)
	}
	if err := replaceAgentLink(slots[0], filepath.Join(root, "current")); err != nil {
		t.Fatal(err)
	}
	bin := filepath.Join(root, "commands")
	if err := os.MkdirAll(filepath.Join(bin, "roami"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := activateAgentBundle(slots[1], bin); err == nil {
		t.Fatal("activation unexpectedly replaced a directory")
	}
	current, err := os.Readlink(filepath.Join(root, "current"))
	if err != nil || current != slots[0] {
		t.Fatal("failed activation changed current release", current, err)
	}
}
