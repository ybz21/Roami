package sessionreview

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/gitcontext"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestIdleReviewPinsChangesAndStopsOnApproval(t *testing.T) {
	ctx := context.Background()
	dir := t.TempDir()
	for _, args := range [][]string{{"init", "-b", "main"}, {"commit", "--allow-empty", "-m", "baseline"}} {
		cmd := exec.Command("git", args...)
		cmd.Dir = dir
		cmd.Env = append(gitcontext.ForDirectory(os.Environ()), "GIT_AUTHOR_NAME=test", "GIT_AUTHOR_EMAIL=test@example.invalid", "GIT_COMMITTER_NAME=test", "GIT_COMMITTER_EMAIL=test@example.invalid")
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("%s: %v", out, err)
		}
	}
	base, err := Baseline(ctx, dir)
	if err != nil {
		t.Fatal(err)
	}
	s := Open(runtime.Runtime{DataDir: t.TempDir()})
	p := Pair{Author: Endpoint{Session: "2026-1120-1200-a001"}, Reviewer: Endpoint{Session: "2026-1120-1200-r001"}, Base: base, Directory: dir, Trigger: "idle"}
	if err := s.Bind(ctx, p); err != nil {
		t.Fatal(err)
	}
	author := p.Author.Session
	if err := s.QueueIdle(ctx, author); !errors.Is(err, ErrNoChanges) {
		t.Fatalf("empty diff: %v", err)
	}
	file := filepath.Join(dir, "new file")
	if err := os.WriteFile(file, []byte("review content"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := s.QueueIdle(ctx, author); err != nil {
		t.Fatal(err)
	}
	var text string
	send := func(to Endpoint, body string) error {
		text = body
		return nil
	}
	if err := s.Deliver(ctx, author, func(Endpoint) bool { return false }, send); err != nil || text != "" {
		t.Fatalf("busy peer received input: %q %v", text, err)
	}
	idle := func(Endpoint) bool { return true }
	if err := s.Deliver(ctx, author, idle, send); err != nil {
		t.Fatal(err)
	}
	p, _ = s.Load(author)
	version := p.Rounds[0].Version
	if !strings.Contains(text, version) || !strings.Contains(text, s.SnapshotPath(author, 1)) || p.Phase != "reviewing" {
		t.Fatal("delivery was not bound to its snapshot")
	}
	if err := os.WriteFile(file, []byte("later changes"), 0600); err != nil {
		t.Fatal(err)
	}
	bytePatch, err := os.ReadFile(s.SnapshotPath(author, 1))
	if err != nil || strings.Contains(string(bytePatch), "later changes") {
		t.Fatal("review snapshot followed the live workspace")
	}
	if err := s.Change(ctx, author, func(p *Pair) (bool, error) {
		return queueVerdict(p, "approved", fmt.Sprintf("r2 rev=%s Wrong round", version))
	}); err == nil {
		t.Fatal("stale verdict accepted")
	}
	if err := s.Change(ctx, author, func(p *Pair) (bool, error) {
		return queueVerdict(p, "approved", fmt.Sprintf("r1 rev=%s Verified patch", version))
	}); err != nil {
		t.Fatal(err)
	}
	if err := s.Deliver(ctx, author, idle, send); err != nil {
		t.Fatal(err)
	}
	p, _ = s.Load(author)
	if p.Phase != "approved" || p.Pending != nil || p.Rounds[0].Result != "Verified patch" {
		t.Fatalf("approval was not recorded: %+v", p)
	}
}

func TestUnknownReviewDeliveryIsNotReplayed(t *testing.T) {
	ctx := context.Background()
	s := Open(runtime.Runtime{DataDir: t.TempDir()})
	p := Pair{Author: Endpoint{Session: "2026-1120-1200-a001"}, Reviewer: Endpoint{Session: "2026-1120-1200-r001"}}
	if err := s.Bind(ctx, p); err != nil {
		t.Fatal(err)
	}
	if err := s.Change(ctx, p.Author.Session, func(p *Pair) (bool, error) {
		p.Pending = &Message{Kind: "request", Round: 1, Started: true}
		return true, nil
	}); err != nil {
		t.Fatal(err)
	}
	if err := s.Deliver(ctx, p.Author.Session, func(Endpoint) bool { return true }, func(Endpoint, string) error {
		t.Error("unknown terminal submission was replayed")
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	got, err := s.Load(p.Author.Session)
	if err != nil || got.Phase != "interrupted" || got.Interrupted != "delivery_unconfirmed" {
		t.Fatalf("interrupted review: %+v %v", got, err)
	}
}
