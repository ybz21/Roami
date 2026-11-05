package modelgateway

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"
	"time"
)

func awaitAdmissionQueue(t *testing.T, handler *Handler, count int) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		handler.mu.Lock()
		waiting := len(handler.admissionQueue)
		handler.mu.Unlock()
		if waiting == count {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("requests did not queue")
}

func TestAdmissionServesOlderWaiterBeforeLaterArrival(t *testing.T) {
	ledger := newLedger(t)
	if err := ledger.Configure(testConfiguration(floatPointer(100))); err != nil {
		t.Fatal(err)
	}
	handler := NewHandler(ledger)
	first, err := handler.admit(context.Background(), "main", "fixture", "session", "first", func() error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	type result struct {
		call Call
		err  error
	}
	results := make(chan result, 2)
	start := func(name string, checked chan struct{}) {
		go func() {
			call, err := handler.admit(ctx, "main", "fixture", "session", name, func() error {
				select {
				case checked <- struct{}{}:
				default:
				}
				return nil
			})
			results <- result{call, err}
		}()
	}
	olderChecked := make(chan struct{}, 1)
	start("older", olderChecked)
	awaitAdmission(t, olderChecked)
	handler.mu.Lock()
	handler.mu.Unlock()

	// Settlement can finish before its goroutine broadcasts admission availability.
	if err := ledger.Settle(first, &Usage{}, 200, "", false); err != nil {
		t.Fatal(err)
	}
	laterChecked := make(chan struct{}, 1)
	start("later", laterChecked)
	var next *result
	select {
	case <-laterChecked:
		select {
		case ready := <-results:
			next = &ready
		case <-time.After(200 * time.Millisecond):
		}
	case <-time.After(200 * time.Millisecond):
	}
	handler.releaseAdmission()
	for index, want := range []string{"older", "later"} {
		if next == nil {
			select {
			case ready := <-results:
				next = &ready
			case <-time.After(2 * time.Second):
				t.Fatal("queued admission did not finish")
			}
		}
		if next.err != nil {
			t.Fatal(next.err)
		}
		if next.call.Request != want {
			t.Errorf("admission %d: got %q, want %q", index+1, next.call.Request, want)
		}
		if err := ledger.Settle(next.call, &Usage{}, 200, "", false); err != nil {
			t.Fatal(err)
		}
		handler.releaseAdmission()
		next = nil
	}
	stats, err := ledger.Statistics(1)
	if err != nil || len(stats.Recent) != 3 || len(stats.Today) != 1 || stats.Today[0].Requests != 3 || stats.Today[0].Pending != 0 || stats.Today[0].Unknown != 0 {
		t.Fatalf("queued accounting changed: %+v %v", stats, err)
	}
}

func TestAdmissionRevalidatesNonHeadWhileUsageIsPending(t *testing.T) {
	ledger := newLedger(t)
	if err := ledger.Configure(testConfiguration(floatPointer(100))); err != nil {
		t.Fatal(err)
	}
	handler := NewHandler(ledger)
	first, err := handler.admit(context.Background(), "main", "fixture", "session", "first", func() error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	type result struct {
		call Call
		err  error
	}
	older, invalidated := make(chan result, 1), make(chan result, 1)
	go func() {
		call, err := handler.admit(ctx, "main", "fixture", "session", "older", func() error { return nil })
		older <- result{call, err}
	}()
	awaitAdmissionQueue(t, handler, 1)
	var revoked atomic.Bool
	go func() {
		call, err := handler.admit(ctx, "main", "fixture", "session", "revoked", func() error {
			if revoked.Load() {
				return errors.New("fixture_route_revoked")
			}
			return nil
		})
		invalidated <- result{call, err}
	}()
	awaitAdmissionQueue(t, handler, 2)
	revoked.Store(true)
	handler.notifyAdmission()
	var rejected *result
	select {
	case value := <-invalidated:
		rejected = &value
	case <-time.After(200 * time.Millisecond):
		t.Error("invalidated non-head request remained blocked behind pending usage")
	}
	if err := ledger.Settle(first, &Usage{}, 200, "", false); err != nil {
		t.Fatal(err)
	}
	handler.releaseAdmission()
	select {
	case value := <-older:
		if value.err != nil {
			t.Fatal(value.err)
		}
		if err := ledger.Settle(value.call, &Usage{}, 200, "", false); err != nil {
			t.Fatal(err)
		}
		handler.releaseAdmission()
	case <-time.After(2 * time.Second):
		t.Fatal("older request did not finish")
	}
	if rejected == nil {
		select {
		case value := <-invalidated:
			rejected = &value
		case <-time.After(2 * time.Second):
			t.Fatal("invalidated request did not finish")
		}
	}
	if rejected.err == nil || rejected.err.Error() != "fixture_route_revoked" || rejected.call.ID != "" {
		t.Fatalf("invalidated request was admitted: %+v", rejected)
	}
	stats, err := ledger.Statistics(1)
	if err != nil || len(stats.Recent) != 2 {
		t.Fatalf("invalidated request changed accounting: %+v %v", stats, err)
	}
}

func TestAdmissionCancellationPreservesRemainingOrder(t *testing.T) {
	for _, cancelled := range []string{"alpha", "beta"} {
		t.Run(cancelled, func(t *testing.T) {
			ledger := newLedger(t)
			if err := ledger.Configure(testConfiguration(floatPointer(100))); err != nil {
				t.Fatal(err)
			}
			handler := NewHandler(ledger)
			first, err := handler.admit(context.Background(), "main", "fixture", "session", "first", func() error { return nil })
			if err != nil {
				t.Fatal(err)
			}
			type result struct {
				name string
				call Call
				err  error
			}
			results := make(chan result, 3)
			names := []string{"alpha", "beta", "gamma"}
			var cancelSelected context.CancelFunc
			for index, name := range names {
				ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
				defer cancel()
				if name == cancelled {
					cancelSelected = cancel
				}
				go func() {
					call, err := handler.admit(ctx, "main", "fixture", "session", name, func() error { return nil })
					results <- result{name, call, err}
				}()
				awaitAdmissionQueue(t, handler, index+1)
			}
			cancelSelected()
			select {
			case value := <-results:
				if value.name != cancelled || !errors.Is(value.err, context.Canceled) || value.call.ID != "" {
					t.Fatalf("cancelled request created a call: %+v", value)
				}
			case <-time.After(2 * time.Second):
				t.Fatal("queued cancellation did not finish")
			}
			awaitAdmissionQueue(t, handler, 2)
			if err := ledger.Settle(first, &Usage{}, 200, "", false); err != nil {
				t.Fatal(err)
			}
			handler.releaseAdmission()
			for _, want := range names {
				if want == cancelled {
					continue
				}
				select {
				case value := <-results:
					if value.name != want || value.err != nil {
						t.Fatalf("remaining admission order changed: got %+v, want %s", value, want)
					}
					if err := ledger.Settle(value.call, &Usage{}, 200, "", false); err != nil {
						t.Fatal(err)
					}
					handler.releaseAdmission()
				case <-time.After(2 * time.Second):
					t.Fatal("remaining admission did not finish")
				}
			}
			awaitAdmissionQueue(t, handler, 0)
			stats, err := ledger.Statistics(1)
			if err != nil || len(stats.Recent) != 3 || stats.Today[0].Pending != 0 || stats.Today[0].Unknown != 0 {
				t.Fatalf("cancellation changed accounting: %+v %v", stats, err)
			}
		})
	}
}

func TestRemovingLimitAdmitsEveryWaiterBeforeActiveCallFinishes(t *testing.T) {
	ledger := newLedger(t)
	if err := ledger.Configure(testConfiguration(floatPointer(100))); err != nil {
		t.Fatal(err)
	}
	handler := NewHandler(ledger)
	first, err := handler.admit(context.Background(), "main", "fixture", "session", "first", func() error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	type result struct {
		call Call
		err  error
	}
	results := make(chan result, 3)
	for index, name := range []string{"alpha", "beta", "gamma"} {
		go func() {
			call, err := handler.admit(ctx, "main", "fixture", "session", name, func() error { return nil })
			results <- result{call, err}
		}()
		awaitAdmissionQueue(t, handler, index+1)
	}
	if err := ledger.Configure(testConfiguration(nil)); err != nil {
		t.Fatal(err)
	}
	handler.notifyAdmission()
	calls := []Call{first}
	for range 3 {
		select {
		case value := <-results:
			if value.err != nil {
				t.Fatal(value.err)
			}
			calls = append(calls, value.call)
		case <-time.After(2 * time.Second):
			t.Fatal("unlimited requests waited for active call settlement")
		}
	}
	stats, err := ledger.Statistics(1)
	if err != nil || len(stats.Recent) != 4 || stats.Today[0].Pending != 4 {
		t.Fatalf("unlimited requests were serialized or lost: %+v %v", stats, err)
	}
	for _, call := range calls {
		if err := ledger.Settle(call, &Usage{}, 200, "", false); err != nil {
			t.Fatal(err)
		}
		handler.releaseAdmission()
	}
	awaitAdmissionQueue(t, handler, 0)
}
