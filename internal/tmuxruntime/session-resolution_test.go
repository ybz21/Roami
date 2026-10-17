package runtime

import (
	"os"
	"path/filepath"
	"testing"
)

func TestStrictResolutionRejectsDuplicateLabelsAndSurvivesRename(t *testing.T) {
	rt := fakeTmux(t, "$0\t1785233330\t2026-0728-1808-0000\tsame\n"+
		"$1\t1785233330\t2026-0728-1808-0001\tsame\n")
	if _, err := rt.ResolveStrict("same"); err == nil || err.Error() != "SESSION_TARGET_AMBIGUOUS" {
		t.Fatalf("ambiguous label: %v", err)
	}
	for _, token := range []string{"$1", "2026-0728-1808-0001"} {
		row, err := rt.ResolveStrict(token)
		if err != nil || row.Name != "2026-0728-1808-0001" {
			t.Fatalf("stable identity: %+v %v", row, err)
		}
	}
	if err := os.WriteFile(filepath.Join(rt.DataDir, "sessions.tsv"), []byte(
		"$1\t1785233330\t2026-0728-1808-0001\tnew label\n"), 0600); err != nil {
		t.Fatal(err)
	}
	row, err := rt.ResolveStrict("2026-0728-1808-0001")
	if err != nil || row.Label != "new label" {
		t.Fatalf("rename changed identity: %+v %v", row, err)
	}
	if _, err := rt.ResolveStrict("same"); err == nil || err.Error() != "SESSION_TARGET_NOT_FOUND" {
		t.Fatalf("old label should not resolve: %v", err)
	}
}

func TestStrictResolutionPrioritizesIDsOverLabels(t *testing.T) {
	rt := fakeTmux(t, "$0\t1785233330\t2026-0728-1808-0000\t2026-0728-1808-0001\n"+
		"$1\t1785233330\t2026-0728-1808-0001\twork\n"+
		"$2\t1785233330\tlegacy-name\tlegacy\n")
	for _, token := range []string{"2026-0728-1808-0001", "$1"} {
		row, err := rt.ResolveStrict(token)
		if err != nil || row.TmuxID != "$1" {
			t.Fatalf("ID shadowed by label: %+v %v", row, err)
		}
	}
	row, err := rt.ResolveStrict(legacyID)
	if err != nil || row.Name != "legacy-name" {
		t.Fatalf("legacy derived ID: %+v %v", row, err)
	}
}

func TestStrictResolutionDistinguishesEmptyAndUnknown(t *testing.T) {
	rt := Runtime{TmuxBin: filepath.Join(t.TempDir(), "missing")}
	if _, err := rt.ObserveSessionRows(); err == nil || err.Error() != "SESSION_OBSERVATION_FAILED" {
		t.Fatalf("unreadable snapshot: %v", err)
	}
	if _, err := rt.ResolveStrict("work"); err == nil || err.Error() != "SESSION_OBSERVATION_FAILED" {
		t.Fatalf("observation failure is not not-found: %v", err)
	}
	rows, err := fakeTmux(t, "").ObserveSessionRows()
	if err != nil || rows == nil || len(rows) != 0 {
		t.Fatalf("known empty: %+v %v", rows, err)
	}
	if _, err := fakeTmux(t, "$1\tbroken\twork\tlabel\n").ObserveSessionRows(); err == nil {
		t.Fatal("invalid observation was silently omitted")
	}
}
