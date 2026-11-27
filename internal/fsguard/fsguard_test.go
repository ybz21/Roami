package fsguard

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestOwnedByCurrentUserAndOpenNoFollow(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "data.bin")

	f, err := OpenNoFollow(target, true, true, 0600)
	if err != nil {
		t.Fatalf("OpenNoFollow create: %v", err)
	}
	_, _ = f.WriteString("hello")
	_ = f.Close()

	info, err := os.Lstat(target)
	if err != nil {
		t.Fatalf("lstat: %v", err)
	}
	if !OwnedByCurrentUser(info) {
		t.Fatalf("expected file created by test to be owned by current user")
	}
	if runtime.GOOS != "windows" {
		if _, ino, ok := FileIdentity(info); !ok || ino == 0 {
			t.Fatalf("expected non-zero inode on unix, got ok=%v ino=%d", ok, ino)
		}
	}

	link := filepath.Join(dir, "link.bin")
	if err := os.Symlink(target, link); err == nil {
		if lf, err := OpenNoFollow(link, false, true, 0600); err == nil {
			_ = lf.Close()
			t.Fatalf("OpenNoFollow must reject symlink")
		}
	}
}
