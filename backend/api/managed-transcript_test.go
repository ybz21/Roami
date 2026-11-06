package api

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestProviderTranscriptIgnoresNewerSameDirectoryConversation(t *testing.T) {
	root := t.TempDir()
	a := "11111111-1111-4111-8111-111111111111"
	b := "22222222-2222-4222-8222-222222222222"
	for _, id := range []string{a, b} {
		file := filepath.Join(root, "rollout-"+id+".jsonl")
		if err := os.WriteFile(file, []byte(`{"type":"session_meta","payload":{"cwd":"/same-project"}}`), 0600); err != nil {
			t.Fatal(err)
		}
	}
	other := filepath.Join(root, "rollout-"+b+".jsonl")
	if err := os.Chtimes(other, time.Now(), time.Now().Add(time.Hour)); err != nil {
		t.Fatal(err)
	}
	if got := providerTranscriptFile(root, "-"+a+".jsonl", false); got != filepath.Join(root, "rollout-"+a+".jsonl") {
		t.Fatalf("wrong provider: %q", got)
	}
	if got := providerTranscriptFile(root, "-missing.jsonl", false); got != "" {
		t.Fatalf("missing provider fell back: %q", got)
	}
	duplicate := filepath.Join(root, "duplicate")
	if err := os.Mkdir(duplicate, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(duplicate, "rollout-"+a+".jsonl"), []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	if got := providerTranscriptFile(root, "-"+a+".jsonl", false); got != "" {
		t.Fatalf("ambiguous provider: %q", got)
	}
}
func TestClaudeProviderTranscriptMatchesExactFilename(t *testing.T) {
	root := t.TempDir()
	id := "11111111-1111-4111-8111-111111111111"
	if err := os.WriteFile(filepath.Join(root, id+".jsonl"), []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	if got := providerTranscriptFile(root, id+".jsonl", true); got != filepath.Join(root, id+".jsonl") {
		t.Fatalf("wrong Claude file: %q", got)
	}
	if transcriptFileWithin(root, root+"-other/file.jsonl") || transcriptFileWithin(root, filepath.Join(root, "..", "foreign")) {
		t.Fatal("root escape accepted")
	}
}
