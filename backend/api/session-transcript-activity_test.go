package api

import (
	"database/sql"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestSessionActivityTranscriptIgnoresMetadataAndKeepsVisibleReplies(t *testing.T) {
	now := time.Date(2026, 11, 23, 3, 30, 0, 0, time.UTC)
	replyAt := now.Add(-time.Minute).Unix()
	tests := []struct {
		kind, line string
		want       int64
	}{
		{"codex", `{"timestamp":"2026-11-23T03:29:00Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"text":"Tip: restart after saving."}]}}`, replyAt},
		{"codex", `{"timestamp":"2026-11-23T03:29:00Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"text":"<environment_context>adjusted</environment_context>"}]}}`, 0},
		{"codex", `{"timestamp":"2026-11-23T03:29:59Z","type":"event_msg","payload":{"type":"token_count"}}`, 0},
		{"codex", `{"timestamp":"2027-11-23T03:29:00Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"text":"Future"}]}}`, 0},
		{"claude", `{"timestamp":"2026-11-23T03:29:00Z","type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Tip: restart after saving."}]}}`, replyAt},
		{"claude", `{"timestamp":"2026-11-23T03:29:00Z","type":"progress","message":{"text":"timer tick"}}`, 0},
	}
	for _, tt := range tests {
		if got := transcriptMessageTime(tt.kind, tt.line, now); got != tt.want {
			t.Errorf("%s transcript time = %d, want %d for %s", tt.kind, got, tt.want, tt.line)
		}
	}
}

func TestSessionActivityTranscriptReadsCompleteRecordsAfterRestart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "record.jsonl")
	appendRecord := func(record string) {
		t.Helper()
		f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
		if err != nil {
			t.Fatal(err)
		}
		defer f.Close()
		if _, err = f.WriteString(record); err != nil {
			t.Fatal(err)
		}
	}
	reply := func(at string) string {
		return `{"timestamp":"` + at + `","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"text":"visible reply"}]}}`
	}
	first := time.Now().Add(-4 * time.Minute).UTC().Truncate(time.Second)
	second := first.Add(time.Minute)
	appendRecord(reply(first.Format(time.RFC3339)) + "\n")
	appendRecord(reply(second.Format(time.RFC3339)))
	fresh := activityTranscript{file: path}
	fresh.read("codex")
	if fresh.at != first.Unix() {
		t.Fatalf("cold start time = %d, want %d", fresh.at, first.Unix())
	}
	appendRecord("\n")
	fresh.read("codex")
	if fresh.at != second.Unix() {
		t.Fatalf("appended reply time = %d, want %d", fresh.at, second.Unix())
	}
	appendRecord(`{"type":"event_msg","payload":{"type":"token_count"}}` + "\n")
	fresh.read("codex")
	if fresh.at != second.Unix() {
		t.Fatalf("metadata update advanced time to %d", fresh.at)
	}
}

func TestSessionActivityCodexFileRejectsAmbiguousAndExternalRecords(t *testing.T) {
	db, err := sql.Open("sqlite", filepath.Join(t.TempDir(), "state.sqlite"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	root := t.TempDir()
	file := filepath.Join(root, "thread.jsonl")
	if _, err := db.Exec("CREATE TABLE threads (id TEXT, rollout_path TEXT)"); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec("INSERT INTO threads VALUES ('same',?), ('same',?), ('other',?)", file, filepath.Join(root, "another.jsonl"), filepath.Join(t.TempDir(), "outside.jsonl")); err != nil {
		t.Fatal(err)
	}
	const query = "SELECT rollout_path FROM threads WHERE id=?"
	if got := uniqueCodexActivityFile(db, root, query, "same"); got != "" {
		t.Fatalf("ambiguous Codex activity used %q", got)
	}
	if got := uniqueCodexActivityFile(db, root, query, "other"); got != "" {
		t.Fatalf("external Codex activity used %q", got)
	}
	if got := uniqueCodexActivityFile(db, root, query+" AND rollout_path=?", "same", file); got != file {
		t.Fatalf("expected exact Codex activity file, got %q", got)
	}
}
