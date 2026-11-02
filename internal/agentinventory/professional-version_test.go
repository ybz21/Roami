package agentinventory

import (
	"context"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

func writeVersionCLI(t *testing.T, path, body string) {
	t.Helper()
	if err := os.WriteFile(path, []byte("#!/bin/sh\n[ \"$#\" -eq 1 ] && [ \"$1\" = --version ] || exit 99\n"+body), 0700); err != nil {
		t.Fatal(err)
	}
}

func TestInstalledVersionsAreCachedAndRefreshAfterReplacement(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", t.TempDir())
	t.Setenv("PATH", dir)
	for _, kind := range []string{"claude", "codex", "opencode", "pi"} {
		writeVersionCLI(t, filepath.Join(dir, kind), "printf x >> '"+filepath.Join(dir, kind+"-runs")+"'\nprintf '"+kind+" 1.0\\n'\n")
	}
	for range 2 {
		rows := DiscoverProfessionalAgents(context.Background())
		for _, row := range rows {
			if !row.Installed || row.Version != row.Kind+" 1.0" || row.VersionState != "available" {
				t.Fatalf("missing version: %+v", row)
			}
			data, err := os.ReadFile(filepath.Join(dir, row.Kind+"-runs"))
			if err != nil || string(data) != "x" {
				t.Fatalf("poll repeated %s probe: %q, %v", row.Kind, data, err)
			}
		}
	}
	if _, err := CheckProfessionalAgent(context.Background(), "codex"); err != nil {
		t.Fatal(err)
	}
	if data, err := os.ReadFile(filepath.Join(dir, "codex-runs")); err != nil || string(data) != "xx" {
		t.Fatalf("explicit check reused cache: %q, %v", data, err)
	}
	path := filepath.Join(dir, "codex")
	writeVersionCLI(t, path+".next", "printf 'codex 2.0\\n'\n")
	if err := os.Rename(path+".next", path); err != nil {
		t.Fatal(err)
	}
	for _, row := range DiscoverProfessionalAgents(context.Background()) {
		if row.Kind == "codex" && row.Version != "codex 2.0" {
			t.Fatalf("replacement kept old version: %+v", row)
		}
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	for _, row := range DiscoverProfessionalAgents(context.Background()) {
		if row.Kind == "codex" && (row.Installed || row.Version != "") {
			t.Fatalf("removed binary kept old version: %+v", row)
		}
	}
}

func TestVersionReadersShareProbeAndCancellationDoesNotPoisonCache(t *testing.T) {
	dir := t.TempDir()
	path, marker := filepath.Join(dir, "opencode"), filepath.Join(dir, "runs")
	writeVersionCLI(t, path, "printf x >> '"+marker+"'\n/bin/sleep 0.1\nprintf 'opencode 1.0\\n'\n")
	row := ProfessionalAgent{Kind: "opencode", Installed: true, Binary: path}
	ctx, cancel := context.WithTimeout(context.Background(), time.Millisecond)
	defer cancel()
	readProfessionalVersion(ctx, &row, false)
	if row.Version != "" {
		t.Fatal("canceled reader waited for the version")
	}
	var pending sync.WaitGroup
	for range 12 {
		pending.Add(1)
		go func() {
			defer pending.Done()
			copy := ProfessionalAgent{Kind: "opencode", Installed: true, Binary: path}
			readProfessionalVersion(context.Background(), &copy, false)
			if copy.Version != "opencode 1.0" {
				t.Errorf("shared probe failed: %+v", copy)
			}
		}()
	}
	pending.Wait()
	data, err := os.ReadFile(marker)
	if err != nil || string(data) != "x" {
		t.Fatalf("concurrent readers repeated probe: %q, %v", data, err)
	}
}

func TestFailedVersionProbeBacksOffAndCanBeRetried(t *testing.T) {
	dir := t.TempDir()
	path, marker := filepath.Join(dir, "pi"), filepath.Join(dir, "runs")
	writeVersionCLI(t, path, "printf x >> '"+marker+"'\nexit 1\n")
	row := ProfessionalAgent{Kind: "pi", Installed: true, Binary: path}
	for range 2 {
		readProfessionalVersion(context.Background(), &row, false)
		if !row.Installed || row.Version != "" || row.VersionState != "unavailable" {
			t.Fatalf("version failure changed installation: %+v", row)
		}
	}
	if data, err := os.ReadFile(marker); err != nil || string(data) != "x" {
		t.Fatalf("failed probe did not back off: %q, %v", data, err)
	}
	professionalVersions.Lock()
	professionalVersions.entries["pi"].until = time.Now().Add(-time.Second)
	professionalVersions.Unlock()
	readProfessionalVersion(context.Background(), &row, false)
	if data, err := os.ReadFile(marker); err != nil || string(data) != "xx" {
		t.Fatalf("expired failure did not retry: %q, %v", data, err)
	}
}
