package api

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/ybz21/Roami/backend/ttmux"
	"github.com/ybz21/Roami/internal/gitcontext"
	"github.com/ybz21/Roami/internal/id"
	"github.com/ybz21/Roami/internal/session"
	life "github.com/ybz21/Roami/internal/sessionlifecycle"
	"github.com/ybz21/Roami/internal/sessionreview"
	"github.com/ybz21/Roami/internal/sessionstore"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestSessionReviewHarness(t *testing.T) {
	mode := os.Getenv("ROAMI_REVIEW_FIXTURE_MODE")
	if mode == "" {
		return
	}
	args := os.Args
	for args[0] != "--" {
		args = args[1:]
	}
	args = args[1:]
	if mode == "send" {
		if err := session.Send(runtime.New(), nil, args, io.Discard); err != nil {
			t.Fatal(err)
		}
		return
	}
	file := args[0]
	if err := os.WriteFile(file+".prompt", []byte(args[1]), 0600); err != nil {
		t.Fatal(err)
	}
	fmt.Println(reviewReadyLine)
	go func() {
		input := bufio.NewScanner(os.Stdin)
		incoming, err := os.Create(file + ".received")
		if err != nil {
			return
		}
		defer incoming.Close()
		for input.Scan() {
			_, _ = fmt.Fprintln(incoming, input.Text())
		}
	}()
	tick := time.NewTicker(25 * time.Millisecond)
	defer tick.Stop()
	for range tick.C {
		contents, err := os.ReadFile(file + ".send")
		if err != nil {
			continue
		}
		var send []string
		if json.Unmarshal(contents, &send) != nil {
			continue
		}
		_ = os.Remove(file + ".send")
		exe, _ := os.Executable()
		cmd := exec.Command(exe, append([]string{"-test.run=^TestSessionReviewHarness$", "--"}, send...)...)
		cmd.Env = append(os.Environ(), "ROAMI_REVIEW_FIXTURE_MODE=send")
		out, err := cmd.CombinedOutput()
		result := "sent"
		if err != nil {
			result = strings.TrimSpace(string(out))
		}
		_ = os.WriteFile(file+".result.tmp", []byte(result), 0600)
		_ = os.Rename(file+".result.tmp", file+".result")
	}
}

func TestSessionReviewIsolatedE2E(t *testing.T) {
	if os.Getenv("ROAMI_REVIEW_TEST_CHILD") != "1" {
		if _, err := exec.LookPath("tmux"); err != nil {
			t.Skip("tmux is unavailable")
		}
		root, _ := filepath.Abs("../..")
		instance := t.TempDir()
		launcher := filepath.Join(root, "scripts/dev/isolated-roami.sh")
		t.Cleanup(func() {
			if out, err := exec.Command(launcher, instance, "--stop").CombinedOutput(); err != nil {
				t.Errorf("stop isolated fixture: %v %s", err, out)
			}
		})
		ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, launcher, instance, "env", "ROAMI_REVIEW_TEST_CHILD=1", os.Args[0], "-test.run=^TestSessionReviewIsolatedE2E$", "-test.v")
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("review fixture: %v\n%s", err, out)
		}
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 65*time.Second)
	defer cancel()
	rt := runtime.New()
	handler := New(ttmux.New("roami"), "", rt.DataDir, "")
	fixture, repo := t.TempDir(), t.TempDir()
	git := func(args ...string) {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", repo}, args...)...)
		cmd.Env = append(gitcontext.ForDirectory(os.Environ()), "GIT_AUTHOR_NAME=test", "GIT_AUTHOR_EMAIL=test@example.invalid", "GIT_COMMITTER_NAME=test", "GIT_COMMITTER_EMAIL=test@example.invalid")
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
	}
	git("init", "-b", "main")
	git("commit", "--allow-empty", "-m", "baseline")

	prepare := func(kind, role string) (string, string) {
		t.Helper()
		binary := filepath.Join(fixture, kind+"-review-fixture")
		if err := os.Symlink(os.Args[0], binary); err != nil {
			t.Fatal(err)
		}
		file := filepath.Join(fixture, role)
		return "ROAMI_REVIEW_FIXTURE_MODE=listen " + shellQuote(binary) + " -test.run=^TestSessionReviewHarness$ -- " + shellQuote(file), file
	}
	authorCommand, authorFile := prepare("codex", "author")
	reviewerCommand, reviewerFile := prepare("claude", "reviewer")
	launch := &life.Launch{Agent: "codex", Command: authorCommand, TaskHeading: "Original task", Task: "Keep 'quotes' and $(literal)", SetupHeading: "Setup", Preamble: "Use {{PATH}}"}
	intent := life.Intent{Name: "review integration", Dir: repo, Worktree: true, Launch: launch, Review: &life.Review{Agent: "claude", Command: reviewerCommand, Trigger: "submit"}}
	operation, err := handler.Lifecycle.Accept(lifecycleID(), id.New(), "review-integration-key", "create", intent)
	if err != nil {
		t.Fatal(err)
	}
	worker := life.Worker{Store: handler.Lifecycle, Steps: handler.lifecycleSteps}
	if err = worker.RunOne(ctx, operation.ID); err != nil {
		t.Fatal(err)
	}
	operation, err = handler.Lifecycle.Get(operation.ID)
	if err != nil || operation.State != "succeeded" {
		t.Fatalf("creation failed: %v %s %s", err, operation.ErrorCode, operation.ErrorDetail)
	}
	store := sessionreview.Open(rt)
	pair, err := store.Load(operation.ResourceID)
	if err != nil {
		t.Fatal(err)
	}
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	if row, ok := meta.Get(pair.Reviewer.Session); !ok || row.Parent != pair.Author.Session || row.CreatedBy != "review" || row.Home != pair.Directory {
		t.Fatalf("review child lineage: %+v", row)
	}
	await := func(path, want string) string {
		t.Helper()
		deadline := time.Now().Add(6 * time.Second)
		for time.Now().Before(deadline) {
			if data, err := os.ReadFile(path); err == nil && strings.Contains(string(data), want) {
				return string(data)
			}
			time.Sleep(30 * time.Millisecond)
		}
		data, _ := os.ReadFile(path)
		t.Fatalf("missing %q in %s: %s", want, path, data)
		return ""
	}
	prompt := await(authorFile+".prompt", "# Peer review")
	if !strings.HasPrefix(prompt, launch.TaskHeading+"\n\n"+launch.Task) || !strings.Contains(prompt, "roami session send "+pair.Reviewer.Session) {
		t.Fatal("author lost the original prompt or peer binding")
	}
	await(reviewerFile+".prompt", "roami session send "+pair.Author.Session)

	sessions := map[string]string{pair.Author.Session: "author", pair.Reviewer.Session: "review"}
	authors := map[string]bool{pair.Author.Session: true}
	probes := map[string]idleReviewProbe{}
	for _, endpoint := range []sessionreview.Endpoint{pair.Author, pair.Reviewer} {
		handler.Live.set(endpoint.Session, liveSnap{Agent: endpoint.Agent, At: time.Now()})
	}
	queue := func(file, to, prompt string) {
		t.Helper()
		_ = os.Remove(file + ".result")
		content, _ := json.Marshal([]string{to, prompt})
		if err := os.WriteFile(file+".send.tmp", content, 0600); err != nil {
			t.Fatal(err)
		}
		if err := os.Rename(file+".send.tmp", file+".send"); err != nil {
			t.Fatal(err)
		}
		await(file+".result", "sent")
	}
	drive := func(phase string) sessionreview.Pair {
		t.Helper()
		handler.driveSessionReviews(sessions, authors, nil, func(string) string { return "" }, probes, time.Now())
		got, err := store.Load(pair.Author.Session)
		if err != nil || got.Phase != phase {
			t.Fatalf("review phase: want %s got %+v %v", phase, got, err)
		}
		return got
	}
	for round := 1; round <= sessionreview.MaxRounds; round++ {
		path := filepath.Join(pair.Directory, "changed.txt")
		summary := fmt.Sprintf("workspace content %d", round)
		if err := os.WriteFile(path, []byte(summary), 0600); err != nil {
			t.Fatal(err)
		}
		queue(authorFile, pair.Reviewer.Session, "[review.request] "+summary)
		request := drive("reviewing")
		version := request.Rounds[round-1].Version
		await(reviewerFile+".received", fmt.Sprintf("[review.request] r%d rev=%s", round, version))
		await(store.SnapshotPath(pair.Author.Session, round), summary)
		queue(reviewerFile, pair.Author.Session, fmt.Sprintf("[review.changes_requested] r%d rev=%s Finding %d", round, version, round))
		want := "changes"
		if round == sessionreview.MaxRounds {
			want = "limit"
		}
		drive(want)
		await(authorFile+".received", fmt.Sprintf("Finding %d", round))
	}
}
