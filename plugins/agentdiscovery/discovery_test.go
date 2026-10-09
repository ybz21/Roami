package agentdiscovery

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestCodexQuotaReadsFreshLocalSnapshot(t *testing.T) {
	root := t.TempDir()
	t.Setenv("CODEX_HOME", root)
	dir := filepath.Join(root, "sessions", "2026", "10", "09")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	line := fmt.Sprintf(`{"timestamp":%q,"payload":{"rate_limits":{"primary":{"used_percent":42,"window_minutes":300,"resets_at":%d},"secondary":{"used_percent":60,"window_minutes":10080,"resets_at":%d}}}}`,
		time.Now().UTC().Format(time.RFC3339Nano), time.Now().Add(time.Hour).Unix(), time.Now().Add(48*time.Hour).Unix())
	if err := os.WriteFile(filepath.Join(dir, "rollout.jsonl"), []byte(line+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	q := codexQuota()
	if q.State != "available" || q.Remaining == nil || *q.Remaining != 58 || q.WindowMin != 300 || len(q.Windows) != 2 || q.Windows[1].Remaining != 40 {
		t.Fatalf("unexpected quota: %+v", q)
	}
}

func TestCodexQuotaRejectsExpiredWindow(t *testing.T) {
	root := t.TempDir()
	t.Setenv("CODEX_HOME", root)
	dir := filepath.Join(root, "sessions")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	line := fmt.Sprintf(`{"timestamp":%q,"payload":{"rate_limits":{"primary":{"used_percent":42,"window_minutes":300,"resets_at":%d}}}}`,
		time.Now().UTC().Format(time.RFC3339Nano), time.Now().Add(-time.Hour).Unix())
	if err := os.WriteFile(filepath.Join(dir, "rollout.jsonl"), []byte(line+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if q := codexQuota(); q.State != "unknown" {
		t.Fatalf("expired snapshot used: %+v", q)
	}
}
