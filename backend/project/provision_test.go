package project

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
)

func TestProvisionReplayConflictAndRemovedTarget(t *testing.T) {
	root := t.TempDir()
	store := NewStore(root, nil)
	base := filepath.Join(root, "sources")
	receipt, err := store.Provision(context.Background(), "one", "Expense App", base, "")
	if err != nil {
		t.Fatal(err)
	}
	if receipt.Key == "" || receipt.Dir != filepath.Join(base, "Expense App") {
		t.Fatalf("receipt: %+v", receipt)
	}
	if err = os.WriteFile(filepath.Join(receipt.Dir, "user.txt"), []byte("preserved"), 0600); err != nil {
		t.Fatal(err)
	}
	replay, err := NewStore(root, nil).Provision(context.Background(), "one", "Expense App", base, "")
	if err != nil || replay != receipt {
		t.Fatalf("replay: %+v %v", replay, err)
	}
	if _, err = store.Provision(context.Background(), "one", "Other", base, ""); err == nil || err.Error() != "PROJECT_PROVISION_KEY_CONFLICT" {
		t.Fatalf("changed key accepted: %v", err)
	}
	if _, err = store.Provision(context.Background(), "two", "Expense App", filepath.Join(root, "elsewhere"), ""); err == nil {
		t.Fatal("same name silently accepted")
	}
	if err = os.RemoveAll(receipt.Dir); err != nil {
		t.Fatal(err)
	}
	if _, err = store.Provision(context.Background(), "one", "Expense App", base, ""); err == nil || err.Error() != "PROJECT_PROVISION_TARGET_REMOVED" {
		t.Fatalf("removed directory resurrected: %v", err)
	}
}

func TestProvisionRecoversOwnedDirectoryAndPreservesAmbiguousDirectory(t *testing.T) {
	for _, owned := range []bool{false, true} {
		t.Run(map[bool]string{false: "unknown", true: "owned"}[owned], func(t *testing.T) {
			root := t.TempDir()
			store := NewStore(root, nil)
			directory := filepath.Join(root, "sources", "New App")
			journal := filepath.Join(root, "project-provisions")
			os.MkdirAll(journal, 0700)
			os.MkdirAll(directory, 0755)
			hash := sha256.Sum256([]byte("lost"))
			token := hex.EncodeToString(hash[:])
			if err := writeProvision(filepath.Join(journal, token+".json"), projectProvision{Directory: directory, Name: "New App"}); err != nil {
				t.Fatal(err)
			}
			if owned {
				if err := writeProvision(filepath.Join(directory, ".roami-project-provision"), token); err != nil {
					t.Fatal(err)
				}
			}
			receipt, err := store.Provision(context.Background(), "lost", "New App", filepath.Dir(directory), "")
			if owned {
				if err != nil || receipt.Key == "" {
					t.Fatalf("did not recover: %+v %v", receipt, err)
				}
			} else if err == nil || err.Error() != "PROJECT_PROVISION_OUTCOME_UNKNOWN" {
				t.Fatalf("unowned directory adopted: %v", err)
			}
		})
	}
}

func TestProvisionDoesNotAdoptAnExistingUserDirectory(t *testing.T) {
	root := t.TempDir()
	store := NewStore(root, nil)
	base := filepath.Join(root, "sources")
	directory := filepath.Join(base, "Existing")
	if err := os.MkdirAll(directory, 0755); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(directory, "user.txt")
	os.WriteFile(file, []byte("keep"), 0600)
	if _, err := store.Provision(context.Background(), "new", "Existing", base, ""); err == nil || err.Error() != "PROJECT_DIRECTORY_EXISTS" {
		t.Fatalf("existing directory adopted: %v", err)
	}
	content, err := os.ReadFile(file)
	if err != nil || string(content) != "keep" {
		t.Fatal("existing content changed")
	}
	if len(store.Entries()) != 0 {
		t.Fatal("unowned directory entered catalog")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err = store.Provision(ctx, "cancelled", "Cancelled", filepath.Join(root, "missing"), ""); err == nil {
		t.Fatal("cancelled provision accepted")
	}
	if _, err = os.Stat(filepath.Join(root, "missing")); !os.IsNotExist(err) {
		t.Fatal("cancelled provision created parent")
	}
}
