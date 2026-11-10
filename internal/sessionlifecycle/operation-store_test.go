package sessionlifecycle

import (
	"context"
	"encoding/json"
	"errors"
	"sync"
	"sync/atomic"
	"testing"

	metadb "github.com/ybz21/Roami/internal/storage"
)

func testStore(t *testing.T) *Store {
	t.Helper()
	dir := t.TempDir()
	db, err := metadb.Open(dir, metadb.Options{HomeDir: dir, DataDir: dir})
	if err != nil {
		t.Fatal(err)
	}
	return New(db, db.Path())
}

func accept(t *testing.T, s *Store, key string) Operation {
	t.Helper()
	o, err := s.Accept("op-"+key, "session-"+key, key, "create", Intent{Name: "task", Dir: t.TempDir()})
	if err != nil {
		t.Fatal(err)
	}
	return o
}

func TestAcceptanceIsDurableAndConcurrentRequestsDeduplicate(t *testing.T) {
	s := testStore(t)
	intent := Intent{Name: "task", Dir: t.TempDir()}
	var wg sync.WaitGroup
	var failures atomic.Int64
	for i := 0; i < 12; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			o, err := s.Accept("one", "reserved", "same-key", "create", intent)
			if err != nil || o.ID != "one" || o.ResourceID != "reserved" {
				failures.Add(1)
			}
		}()
	}
	wg.Wait()
	if failures.Load() != 0 {
		t.Fatalf("%d failed requests", failures.Load())
	}
	reopened := New(s.DB, s.LockDir[:len(s.LockDir)-len(".lifecycle-locks")])
	o, err := reopened.ByKey("same-key")
	if err != nil || o.State != "queued" {
		t.Fatalf("lost acceptance: %+v %v", o, err)
	}
	if _, err = s.Accept("other", "another", "same-key", "create", Intent{Name: "changed"}); !errors.Is(err, ErrRequestKey) {
		t.Fatalf("changed intent: %v", err)
	}
	var events int
	if err = s.DB.QueryRow("SELECT count(*) FROM session_lifecycle_events").Scan(&events); err != nil || events != 1 {
		t.Fatalf("events=%d err=%v", events, err)
	}
}

func TestClosingFencesInputAndDescendantWorkspaceUntilRetention(t *testing.T) {
	s := testStore(t)
	dir := t.TempDir()
	o, err := s.Accept("close", "resource", "close-key", "close", Intent{Path: dir, Mode: "discard"})
	if err != nil {
		t.Fatal(err)
	}
	for _, check := range [][2]string{{"resource", ""}, {"", dir + "/child"}} {
		if err = s.Check(context.Background(), check[0], check[1]); err == nil {
			t.Fatal("closing resource was reusable")
		}
	}
	if err = s.Check(WithOperation(context.Background(), o.ID), "resource", dir); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Accept("duplicate", "resource", "different-key", "close", o.Intent); !errors.Is(err, ErrConflict) {
		t.Fatalf("duplicate close: %v", err)
	}
	o, err = s.Mutate(o.ID, o.Revision, func(o *Operation) error { o.State = "attention"; return nil })
	if err != nil {
		t.Fatal(err)
	}
	if err = s.Check(context.Background(), "", dir); err == nil {
		t.Fatal("failed cleanup released workspace")
	}
	_, err = s.Mutate(o.ID, o.Revision, func(o *Operation) error { o.State = "succeeded"; o.Intent.Mode = "keep"; return nil })
	if err != nil {
		t.Fatal(err)
	}
	if err = s.Check(context.Background(), "", dir); err != nil {
		t.Fatal(err)
	}
}

func TestWorkerResumesOnlyUnconfirmedStageAfterRestart(t *testing.T) {
	s := testStore(t)
	o := accept(t, s, "restart-key")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	var prepared, finished int
	worker := Worker{Store: s, Steps: func(Operation) []Step {
		return []Step{
			{Name: "prepare", Run: func(context.Context, Operation) (any, error) { prepared++; return "receipt", nil }},
			{Name: "finish", Run: func(context.Context, Operation) (any, error) { finished++; cancel(); return nil, ctx.Err() }},
		}
	}}
	if err := worker.RunOne(ctx, o.ID); !errors.Is(err, context.Canceled) {
		t.Fatalf("interruption: %v", err)
	}
	interrupted, err := s.Get(o.ID)
	if err != nil || interrupted.State != "running" || !interrupted.Has("prepare") || interrupted.Has("finish") {
		t.Fatalf("bad checkpoint: %+v %v", interrupted, err)
	}
	worker.Steps = func(Operation) []Step {
		return []Step{
			{Name: "prepare", Run: func(context.Context, Operation) (any, error) { prepared++; return nil, nil }},
			{Name: "finish", Run: func(context.Context, Operation) (any, error) { finished++; return true, nil }},
		}
	}
	if err = worker.RunOne(context.Background(), o.ID); err != nil {
		t.Fatal(err)
	}
	done, _ := s.Get(o.ID)
	if done.State != "succeeded" || prepared != 1 || finished != 2 || done.Epoch != 2 {
		t.Fatalf("replayed confirmed work: %+v prepared=%d finished=%d", done, prepared, finished)
	}
}

func TestFileLockFencesOldWorkerAndRevisionFencesOldReceipt(t *testing.T) {
	s := testStore(t)
	o := accept(t, s, "locked-key")
	unlock, err := s.Lock("operation:"+o.ID, false, true)
	if err != nil {
		t.Fatal(err)
	}
	ran := false
	worker := Worker{Store: New(s.DB, s.LockDir[:len(s.LockDir)-len(".lifecycle-locks")]), Steps: func(Operation) []Step { ran = true; return nil }}
	if err = worker.RunOne(context.Background(), o.ID); err == nil || ran {
		t.Fatal("another process could execute while old worker owns lock")
	}
	unlock()
	next, err := s.Mutate(o.ID, o.Revision, func(o *Operation) error { o.CancelRequested = true; return nil })
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.Mutate(o.ID, o.Revision, func(o *Operation) error { o.State = "succeeded"; return nil }); !errors.Is(err, ErrConflict) {
		t.Fatal("old receipt overwrote cancellation")
	}
	if err = worker.RunOne(context.Background(), next.ID); err != nil {
		t.Fatal(err)
	}
	done, _ := s.Get(o.ID)
	if done.State != "cancelled" {
		t.Fatalf("cancel lost: %+v", done)
	}
}

func TestFailuresKeepConfirmedStopAndPendingReservations(t *testing.T) {
	s := testStore(t)
	o, err := s.Accept("close", "resource", "cleanup-key", "close", Intent{Path: t.TempDir(), Mode: "discard"})
	if err != nil {
		t.Fatal(err)
	}
	calls := 0
	worker := Worker{Store: s, Steps: func(Operation) []Step {
		return []Step{
			{Name: "stop", Run: func(context.Context, Operation) (any, error) { calls++; return true, nil }},
			{Name: "remove", Run: func(context.Context, Operation) (any, error) {
				return nil, &Failure{Code: "LIFECYCLE_WORKSPACE_CHANGED"}
			}},
		}
	}}
	if err = worker.RunOne(context.Background(), o.ID); err != nil {
		t.Fatal(err)
	}
	failed, _ := s.Get(o.ID)
	if failed.State != "attention" || !failed.Has("stop") || failed.Has("remove") {
		t.Fatalf("lost independent outcomes: %+v", failed)
	}
	if err = worker.RunOne(context.Background(), o.ID); err != nil || calls != 1 {
		t.Fatal("attention was automatically replayed")
	}
	if err = s.Check(context.Background(), "", o.Intent.Path); err == nil {
		t.Fatal("cleanup failure released reservation")
	}
}

func TestPreparingWorkspaceReservationBlocksReuseBeforeSessionExists(t *testing.T) {
	store := testStore(t)
	op := accept(t, store, "preparing-key")
	directory := t.TempDir()
	encoded, err := json.Marshal(map[string]string{"path": directory})
	if err != nil {
		t.Fatal(err)
	}
	op, err = store.Mutate(op.ID, op.Revision, func(o *Operation) error { o.Receipts["workspace-intent"] = encoded; return nil })
	if err != nil {
		t.Fatal(err)
	}
	if err = store.Check(context.Background(), "", directory+"/child"); err == nil {
		t.Fatal("preparing workspace accepted another writer")
	}
	if err = store.Check(WithOperation(context.Background(), op.ID), op.ResourceID, directory); err != nil {
		t.Fatal(err)
	}
}
