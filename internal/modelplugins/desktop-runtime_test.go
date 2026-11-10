package modelplugins

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestVerifiedDesktopPackageAndEnvironment(t *testing.T) {
	source := os.Getenv("ROAMI_MAGPIE_FIXTURES")
	if source == "" {
		t.Skip("set ROAMI_MAGPIE_FIXTURES to verify the audited upstream desktop package")
	}
	dir := t.TempDir()
	for _, name := range doubaoRuntimeFiles {
		data, err := os.ReadFile(filepath.Join(source, "doubao-work", name))
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(filepath.Join(dir, name), data, 0600); err != nil {
			t.Fatal(err)
		}
	}
	data, err := os.ReadFile(filepath.Join(source, "doubao-work", "doubao-work.test.mjs"))
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(dir, "doubao-work.test.mjs"), data, 0600); err != nil {
		t.Fatal(err)
	}
	if !trustedDoubaoDirectory(dir) {
		t.Fatal("unmodified official Doubao Work 0.1.5 was not recognized")
	}
	root := t.TempDir()
	state := filepath.Join(root, "state")
	if err := os.Mkdir(state, 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("ROAMI_WEB_PASSWORD", "fixture-private-environment")
	command, err := desktopCommand(SandboxPaths{Bun: "/runtime/bun", Runtime: "/runtime/host", Package: dir, State: state}, "darwin", root, "")
	if err != nil {
		t.Fatal(err)
	}
	if command.Dir != state || !strings.Contains(strings.Join(command.Args, " "), "--no-install") {
		t.Fatal("desktop worker did not use private state and disable install")
	}
	for _, entry := range command.Env {
		if strings.HasPrefix(entry, "ROAMI_") || strings.Contains(entry, "fixture-private-environment") {
			t.Fatal("host credentials inherited by desktop worker")
		}
	}
	// Git's Windows line-ending conversion preserves the same audited code.
	entry := filepath.Join(dir, "index.mjs")
	original, _ := os.ReadFile(entry)
	_ = os.WriteFile(entry, []byte(strings.ReplaceAll(string(original), "\n", "\r\n")), 0600)
	if !trustedDoubaoDirectory(dir) {
		t.Fatal("CRLF conversion changed the audited code identity")
	}
	_ = os.WriteFile(entry, append(original, []byte("\nexport const changed=true\n")...), 0600)
	if trustedDoubaoDirectory(dir) {
		t.Fatal("modified desktop plugin was trusted")
	}
	if _, err = desktopCommand(SandboxPaths{Package: dir, State: state}, "darwin", root, ""); err == nil {
		t.Fatal("modified plugin received native desktop access")
	}
}
