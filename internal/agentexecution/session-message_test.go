package agentexecution

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func messageService(t *testing.T) Service {
	t.Helper()
	s := testService(t)
	script := fmt.Sprintf(`#!/bin/sh
root=%s
case "$1" in
 list-sessions) printf '$1\t1792200000\t2026-1018-0900-0001\tmessage-test\n' ;;
 list-panes) printf '2026-1018-0900-0001\t$1\t1792200000\tserver\t%%%%3\t%d\t%%s\n' "$root" ;;
 load-buffer) cat > "$root/received" ;;
 paste-buffer) printf 'paste\n' >> "$root/submits"; test ! -f "$root/fail" ;;
 send-keys|delete-buffer) exit 0 ;;
 *) exit 1 ;;
esac
`, quote(s.Runtime.DataDir), os.Getpid())
	s.Runtime.TmuxBin = filepath.Join(s.Runtime.DataDir, "tmux")
	if e := os.WriteFile(s.Runtime.TmuxBin, []byte(script), 0700); e != nil {
		t.Fatal(e)
	}
	return s
}
func TestMessageDeliveryHasOneSubmissionAndDoesNotClaimExecutionCompletion(t *testing.T) {
	s := messageService(t)
	spec := MessageSpec{Key: "one", SessionID: "message-test", Text: "line one\nline two"}
	r, e := s.SendMessage(spec)
	if e != nil {
		t.Fatal(e)
	}
	if r.State != "delivered" || !r.OutcomeKnown || r.ExecutionTracked || r.SentMS == 0 {
		t.Fatalf("invalid receipt: %+v", r)
	}
	for i := 0; i < 2; i++ {
		again, e := s.SendMessage(spec)
		if e != nil || again != r {
			t.Fatalf("replay=%+v %v", again, e)
		}
	}
	body, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "received"))
	if string(body) != spec.Text {
		t.Fatalf("prompt=%q", body)
	}
	submits, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
	if strings.Count(string(submits), "paste") != 1 {
		t.Fatalf("duplicate submission: %s", submits)
	}
	spec.Text = "different"
	if _, e = s.SendMessage(spec); e == nil || e.Error() != "MESSAGE_KEY_CONFLICT" {
		t.Fatalf("conflict=%v", e)
	}
}
func TestPartialMessageDeliveryIsUnknownAndNeverReplayed(t *testing.T) {
	s := messageService(t)
	if e := os.WriteFile(filepath.Join(s.Runtime.DataDir, "fail"), nil, 0600); e != nil {
		t.Fatal(e)
	}
	spec := MessageSpec{Key: "partial", SessionID: "message-test", Text: "do work"}
	r, e := s.SendMessage(spec)
	if e != nil || r.State != "unknown" || r.OutcomeKnown {
		t.Fatalf("receipt=%+v error=%v", r, e)
	}
	_ = os.Remove(filepath.Join(s.Runtime.DataDir, "fail"))
	again, e := s.SendMessage(spec)
	if e != nil || again.State != "unknown" {
		t.Fatalf("replayed: %+v %v", again, e)
	}
	submits, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
	if strings.Count(string(submits), "paste") != 1 {
		t.Fatalf("replayed unknown: %s", submits)
	}
}
