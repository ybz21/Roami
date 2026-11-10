package sessionlifecycle

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"syscall"
	"time"
)

// File locks fence actual side effects across processes, including a worker with an expired lease.
func (s *Store) Lock(key string, shared, nonblocking bool) (func(), error) {
	if err := os.MkdirAll(s.LockDir, 0700); err != nil {
		return nil, err
	}
	name := fmt.Sprintf("%x", sha256.Sum256([]byte(key)))
	f, err := os.OpenFile(filepath.Join(s.LockDir, name), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	flags := syscall.LOCK_EX
	if shared {
		flags = syscall.LOCK_SH
	}
	if nonblocking {
		flags |= syscall.LOCK_NB
	}
	if err = syscall.Flock(int(f.Fd()), flags); err != nil {
		f.Close()
		return nil, err
	}
	return func() { _ = syscall.Flock(int(f.Fd()), syscall.LOCK_UN); _ = f.Close() }, nil
}

func (s *Store) Acquire(ctx context.Context, key string, shared bool) (func(), error) {
	ticker := time.NewTicker(20 * time.Millisecond)
	defer ticker.Stop()
	for {
		release, err := s.Lock(key, shared, true)
		if err == nil {
			return release, nil
		}
		if !errors.Is(err, syscall.EWOULDBLOCK) && !errors.Is(err, syscall.EAGAIN) {
			return nil, err
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-ticker.C:
		}
	}
}

type Failure struct {
	Code string
	Err  error
}

func (f *Failure) Error() string {
	if f.Err != nil {
		return f.Err.Error()
	}
	return f.Code
}

type Step struct {
	Name string
	Run  func(context.Context, Operation) (any, error)
}
type Worker struct {
	Store   *Store
	Steps   func(Operation) []Step
	Changed func(Operation)
}

func (w *Worker) checkpoint(o Operation, fn func(*Operation) error) (Operation, error) {
	next, err := w.Store.Mutate(o.ID, o.Revision, fn)
	if err == nil && w.Changed != nil {
		w.Changed(next)
	}
	return next, err
}

func (w *Worker) RunOne(ctx context.Context, id string) error {
	unlock, err := w.Store.Lock("operation:"+id, false, true)
	if err != nil {
		return err
	}
	defer unlock()
	o, err := w.Store.Get(id)
	if err != nil {
		return err
	}
	if o.Terminal() || o.State == "attention" {
		return nil
	}
	if o.Kind == "close" {
		release, e := w.Store.Acquire(ctx, "resource:"+o.ResourceID, false)
		if e != nil {
			return e
		}
		defer release()
		if o.Intent.Path != "" {
			release, e := w.Store.Acquire(ctx, "workspace:"+CanonicalPath(o.Intent.Path), false)
			if e != nil {
				return e
			}
			defer release()
		}
	}
	o, err = w.checkpoint(o, func(o *Operation) error { o.State = "running"; o.Epoch++; return nil })
	if err != nil {
		return err
	}
	ctx = WithOperation(ctx, o.ID)
	for _, step := range w.Steps(o) {
		latest, e := w.Store.Get(id)
		if e != nil {
			return e
		}
		o = latest
		completed := o.Has(step.Name)
		if o.CancelRequested && step.Name == "compensate" {
			if result, e := Result[any](o, step.Name); e == nil && result == nil {
				completed = false
			}
		}
		if completed {
			continue
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
		o, err = w.checkpoint(o, func(o *Operation) error { o.Stage = step.Name; return nil })
		if err != nil {
			return err
		}
		started := time.Now()
		stepContext, stop := context.WithTimeout(ctx, 2*time.Minute)
		result, e := step.Run(stepContext, o)
		stop()
		latest, readErr := w.Store.Get(id)
		if readErr != nil {
			return readErr
		}
		o = latest
		if e != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			code := "LIFECYCLE_STEP_FAILED"
			var failure *Failure
			if errors.As(e, &failure) {
				code = failure.Code
			}
			_, err = w.checkpoint(o, func(o *Operation) error {
				o.State = "attention"
				o.ErrorCode = code
				o.ErrorDetail = e.Error()
				return nil
			})
			return err
		}
		receipt, _ := json.Marshal(struct {
			Result     any   `json:"result"`
			DurationMS int64 `json:"durationMs"`
		}{result, time.Since(started).Milliseconds()})
		o, err = w.checkpoint(o, func(o *Operation) error {
			o.Receipts[step.Name] = receipt
			o.ErrorCode = ""
			o.ErrorDetail = ""
			return nil
		})
		if err != nil {
			return err
		}
	}
	_, err = w.checkpoint(o, func(o *Operation) error {
		if o.CancelRequested {
			if o.Has("compensate") {
				if result, e := Result[any](*o, "compensate"); e == nil && result == nil {
					o.State = "queued"
					return nil
				}
			}
			o.State = "cancelled"
		} else {
			o.State = "succeeded"
		}
		return nil
	})
	return err
}

func Result[T any](o Operation, stage string) (T, error) {
	var envelope struct {
		Result T `json:"result"`
	}
	err := o.Receipt(stage, &envelope)
	return envelope.Result, err
}

// Control work has its own lane so a slow fetch cannot delay stopping a session.
func (w *Worker) Start(ctx context.Context) func() {
	var lanes sync.WaitGroup
	for _, kind := range []string{"create", "close"} {
		lanes.Add(1)
		go func(kind string) { defer lanes.Done(); w.lane(ctx, kind) }(kind)
	}
	return lanes.Wait
}
func (w *Worker) lane(ctx context.Context, kind string) {
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	active := make(chan struct{}, 4)
	var workers sync.WaitGroup
	defer workers.Wait()
	for {
		if ids, err := w.Store.Pending(kind); err == nil {
			for _, id := range ids {
				select {
				case active <- struct{}{}:
					workers.Add(1)
					go func(id string) { defer workers.Done(); defer func() { <-active }(); _ = w.RunOne(ctx, id) }(id)
				default:
				}
			}
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
