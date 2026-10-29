package modelgateway

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestActiveUsageAdmission(t *testing.T) {
	for _, test := range []struct {
		name       string
		limit      *float64
		firstBody  string
		secondCode int
		secondCall bool
	}{
		{"within limit", floatPointer(10), billableEvents, 200, true},
		{"limit reached", floatPointer(2), billableEvents, 402, false},
		{"unknown after settlement", floatPointer(10), "data: {\"choices\":[]}\n\n", 409, false},
		{"unlimited stays concurrent", nil, billableEvents, 200, true},
	} {
		t.Run(test.name, func(t *testing.T) {
			ledger := newLedger(t)
			if err := ledger.Configure(testConfiguration(test.limit)); err != nil {
				t.Fatal(err)
			}
			entered, release := make(chan struct{}), make(chan struct{})
			var once sync.Once
			unblock := func() { once.Do(func() { close(release) }) }
			var hits atomic.Int32
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				first := hits.Add(1) == 1
				if first {
					close(entered)
					<-release
				}
				w.Header().Set("Content-Type", "text/event-stream")
				body := billableEvents
				if first {
					body = test.firstBody
				}
				_, _ = io.WriteString(w, body)
			}))
			defer upstream.Close()
			defer unblock()
			handler := NewHandler(ledger)
			first, second := httptest.NewRecorder(), httptest.NewRecorder()
			firstDone, secondDone := make(chan struct{}), make(chan struct{})
			go func() { defer close(firstDone); handler.ServeHTTP(first, modelRequest(upstream.URL)) }()
			awaitAdmission(t, entered)
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			go func() {
				defer close(secondDone)
				handler.ServeHTTP(second, modelRequest(upstream.URL).WithContext(ctx))
			}()
			early := false
			if test.limit == nil {
				awaitAdmission(t, secondDone)
				early = true
			} else {
				select {
				case <-secondDone:
					early = true
				case <-time.After(50 * time.Millisecond):
				}
			}
			unblock()
			awaitAdmission(t, firstDone)
			awaitAdmission(t, secondDone)
			if early != (test.limit == nil) {
				t.Fatalf("pending request was rejected or unlimited request was serialized: early=%t code=%d", early, second.Code)
			}
			if first.Code != 200 || second.Code != test.secondCode {
				t.Fatalf("responses: first=%d second=%d %s", first.Code, second.Code, second.Body.String())
			}
			want := 1
			if test.secondCall {
				want++
			}
			stats, err := ledger.Statistics(1)
			if err != nil || int(hits.Load()) != want || len(stats.Recent) != want {
				t.Fatalf("unexpected upstream attempt or ledger row: hits=%d rows=%d err=%v", hits.Load(), len(stats.Recent), err)
			}
			if test.name == "unknown after settlement" && second.Header().Get("X-Roami-Model-Error") != "MODEL_PROXY_USAGE_UNKNOWN" {
				t.Fatal("settled unknown usage protection lost")
			}
		})
	}
}

func TestCancelledAdmissionDoesNotCreateCallOrReplay(t *testing.T) {
	ledger := newLedger(t)
	if err := ledger.Configure(testConfiguration(floatPointer(10))); err != nil {
		t.Fatal(err)
	}
	entered, release := make(chan struct{}), make(chan struct{})
	var once sync.Once
	unblock := func() { once.Do(func() { close(release) }) }
	var hits atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if hits.Add(1) == 1 {
			close(entered)
			<-release
		}
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, billableEvents)
	}))
	defer upstream.Close()
	defer unblock()
	handler := NewHandler(ledger)
	firstDone := make(chan struct{})
	go func() { defer close(firstDone); handler.ServeHTTP(httptest.NewRecorder(), modelRequest(upstream.URL)) }()
	awaitAdmission(t, entered)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	second, secondDone := httptest.NewRecorder(), make(chan struct{})
	go func() {
		defer close(secondDone)
		handler.ServeHTTP(second, modelRequest(upstream.URL).WithContext(ctx))
	}()
	select {
	case <-secondDone:
		unblock()
		awaitAdmission(t, firstDone)
		t.Fatal("pending admission returned before cancellation")
	case <-time.After(50 * time.Millisecond):
	}
	cancel()
	awaitAdmission(t, secondDone)
	stats, err := ledger.Statistics(1)
	if err != nil || len(stats.Recent) != 1 || stats.Recent[0].State != "pending" || second.Body.Len() != 0 {
		t.Fatalf("cancelled wait created or changed accounting: %+v %v", stats.Recent, err)
	}
	unblock()
	awaitAdmission(t, firstDone)
	third := httptest.NewRecorder()
	handler.ServeHTTP(third, modelRequest(upstream.URL))
	if third.Code != 200 || hits.Load() != 2 {
		t.Fatalf("cancelled admission replayed or blocked later calls: code=%d hits=%d", third.Code, hits.Load())
	}
}

func TestAdmissionRechecksChangedDailyPolicy(t *testing.T) {
	ledger := newLedger(t)
	if err := ledger.Configure(testConfiguration(nil)); err != nil {
		t.Fatal(err)
	}
	entered, release := make(chan struct{}), make(chan struct{})
	var once sync.Once
	unblock := func() { once.Do(func() { close(release) }) }
	var hits atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if hits.Add(1) == 1 {
			close(entered)
			<-release
		}
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, billableEvents)
	}))
	defer upstream.Close()
	defer unblock()
	handler := NewHandler(ledger)
	firstDone := make(chan struct{})
	go func() { defer close(firstDone); handler.ServeHTTP(httptest.NewRecorder(), modelRequest(upstream.URL)) }()
	awaitAdmission(t, entered)
	setPolicy := func(limit *float64) {
		raw, err := json.Marshal(testConfiguration(limit))
		if err != nil {
			t.Fatal(err)
		}
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, httptest.NewRequest("PUT", "/v1/model-gateway/settings", strings.NewReader(string(raw))))
		if w.Code != 200 {
			t.Fatalf("policy change: %d %s", w.Code, w.Body.String())
		}
	}
	setPolicy(floatPointer(10))
	second, secondDone := httptest.NewRecorder(), make(chan struct{})
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	go func() {
		defer close(secondDone)
		handler.ServeHTTP(second, modelRequest(upstream.URL).WithContext(ctx))
	}()
	select {
	case <-secondDone:
		unblock()
		awaitAdmission(t, firstDone)
		t.Fatal("enabling limit during an active call rejected the waiting request")
	case <-time.After(50 * time.Millisecond):
	}
	setPolicy(nil)
	awaitAdmission(t, secondDone)
	if second.Code != 200 || hits.Load() != 2 {
		t.Fatalf("removing limit did not release waiting request: %d hits=%d", second.Code, hits.Load())
	}
	unblock()
	awaitAdmission(t, firstDone)
}

func TestUnownedPendingCallIsNotWaitedOnOrReplayed(t *testing.T) {
	ledger := newLedger(t)
	if err := ledger.Configure(testConfiguration(floatPointer(10))); err != nil {
		t.Fatal(err)
	}
	if _, err := ledger.Admit("worker", "fixture", "old-session", "old-request"); err != nil {
		t.Fatal(err)
	}
	w := httptest.NewRecorder()
	NewHandler(ledger).ServeHTTP(w, modelRequest("https://must-not-connect.invalid"))
	if w.Code != 409 || w.Header().Get("X-Roami-Model-Error") != "MODEL_PROXY_USAGE_PENDING" {
		t.Fatalf("unowned pending protection lost: %d %s", w.Code, w.Body.String())
	}
	stats, err := ledger.Statistics(1)
	if err != nil || len(stats.Recent) != 1 || stats.Recent[0].Request != "old-request" {
		t.Fatalf("pending history changed: %+v %v", stats.Recent, err)
	}
}

func TestConcurrentAdmissionSettlesEveryRequestOnce(t *testing.T) {
	ledger := newLedger(t)
	if err := ledger.Configure(testConfiguration(floatPointer(100))); err != nil {
		t.Fatal(err)
	}
	var hits, active, maximum atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		current := active.Add(1)
		defer active.Add(-1)
		for previous := maximum.Load(); current > previous; previous = maximum.Load() {
			if maximum.CompareAndSwap(previous, current) {
				break
			}
		}
		time.Sleep(5 * time.Millisecond)
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, billableEvents)
	}))
	defer upstream.Close()
	handler := NewHandler(ledger)
	var wait sync.WaitGroup
	codes := make(chan int, 16)
	for range 16 {
		wait.Add(1)
		go func() {
			defer wait.Done()
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			w := httptest.NewRecorder()
			handler.ServeHTTP(w, modelRequest(upstream.URL).WithContext(ctx))
			codes <- w.Code
		}()
	}
	wait.Wait()
	close(codes)
	for code := range codes {
		if code != 200 {
			t.Fatalf("concurrent request rejected: %d", code)
		}
	}
	stats, err := ledger.Statistics(1)
	if err != nil || hits.Load() != 16 || maximum.Load() != 1 || len(stats.Recent) != 16 || stats.Today[0].Cost != "32.000000000" {
		t.Fatalf("concurrent accounting mismatch: hits=%d maximum=%d stats=%+v err=%v", hits.Load(), maximum.Load(), stats, err)
	}
}

func floatPointer(value float64) *float64 { return &value }

func awaitAdmission(t *testing.T, done <-chan struct{}) {
	t.Helper()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("admission did not finish")
	}
}
