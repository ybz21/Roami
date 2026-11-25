package filelock

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestExclusiveAndNonBlockingLock(t *testing.T) {
	path := filepath.Join(t.TempDir(), "test.lock")
	f1, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		t.Fatalf("open f1: %v", err)
	}
	defer f1.Close()

	unlock1, err := Lock(f1, false, true)
	if err != nil {
		t.Fatalf("Lock f1: %v", err)
	}

	f2, err := os.OpenFile(path, os.O_RDWR, 0600)
	if err != nil {
		t.Fatalf("open f2: %v", err)
	}
	defer f2.Close()

	if _, err := Lock(f2, false, true); !errors.Is(err, ErrWouldBlock) {
		t.Fatalf("expected ErrWouldBlock while f1 holds lock, got %v", err)
	}

	if err := unlock1(); err != nil {
		t.Fatalf("unlock1: %v", err)
	}
	// Unlock must be idempotent.
	if err := unlock1(); err != nil {
		t.Fatalf("second unlock1: %v", err)
	}

	unlock2, err := Lock(f2, false, true)
	if err != nil {
		t.Fatalf("Lock f2 after unlock1: %v", err)
	}
	if err := unlock2(); err != nil {
		t.Fatalf("unlock2: %v", err)
	}
}

func TestSharedLocksCoexist(t *testing.T) {
	path := filepath.Join(t.TempDir(), "shared.lock")
	f1, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		t.Fatalf("open f1: %v", err)
	}
	defer f1.Close()
	f2, err := os.OpenFile(path, os.O_RDWR, 0600)
	if err != nil {
		t.Fatalf("open f2: %v", err)
	}
	defer f2.Close()

	u1, err := Lock(f1, true, true)
	if err != nil {
		t.Fatalf("shared lock 1: %v", err)
	}
	defer func() { _ = u1() }()

	u2, err := Lock(f2, true, true)
	if err != nil {
		t.Fatalf("shared lock 2 should coexist: %v", err)
	}
	defer func() { _ = u2() }()
}
