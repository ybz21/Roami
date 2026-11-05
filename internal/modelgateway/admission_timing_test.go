package modelgateway

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestAdmissionTimingAccumulatesCatalogFailover(t *testing.T) {
	var hits atomic.Int32
	backup := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		_, _ = io.WriteString(w, `{"status":"completed","usage":{"input_tokens":5,"output_tokens":3}}`)
	}))
	defer backup.Close()
	primary := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("closed primary received a request")
	}))
	primary.Close()
	handler := catalogHandler(t, primary.URL, "openai-responses")
	if err := handler.Ledger.Configure(testConfiguration(floatPointer(10))); err != nil {
		t.Fatal(err)
	}
	handler.Catalog.value.Sources = append(handler.Catalog.value.Sources, ModelSource{ID: "backup", Name: "Backup", BaseURL: backup.URL, Protocol: "openai-responses", AuthMode: "bearer"})
	handler.Catalog.value.Models[0].Strategy = "failover"
	handler.Catalog.value.Models[0].Candidates = append(handler.Catalog.value.Models[0].Candidates, ModelCandidate{"backup", "fixture"})
	prime, err := handler.admit(context.Background(), "main", "fixture", "", "timing-control", func() error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	var once sync.Once
	release := func() {
		once.Do(func() {
			if err := handler.Ledger.Settle(prime, &Usage{}, 200, "", false); err != nil {
				t.Error(err)
			}
			handler.releaseAdmission()
		})
	}
	done := make(chan struct{})
	var response *httptest.ResponseRecorder
	go func() {
		defer close(done)
		response = catalogRequest(handler, "/v1/responses", `{"model":"coding-main","input":"synthetic timing control"}`)
	}()
	defer func() { release(); awaitAdmission(t, done) }()
	awaitAdmissionQueue(t, handler, 1)
	time.Sleep(20 * time.Millisecond)
	release()
	awaitAdmission(t, done)
	value, err := strconv.ParseInt(response.Header().Get("X-Roami-Model-Admission-Ms"), 10, 64)
	if err != nil || value < 20 || response.Code != 200 || hits.Load() != 1 {
		t.Fatalf("failover lost earlier admission time: %q code=%d hits=%d err=%v", response.Header().Get("X-Roami-Model-Admission-Ms"), response.Code, hits.Load(), err)
	}
	stats, err := handler.Ledger.Statistics(1)
	if err != nil || len(stats.Recent) != 3 {
		t.Fatalf("failover changed accounting rows: %d %v", len(stats.Recent), err)
	}
}

func TestAdmissionTimingExcludesUpstreamAndIgnoresProviderHeader(t *testing.T) {
	for _, catalog := range []bool{false, true} {
		t.Run(strconv.FormatBool(catalog), func(t *testing.T) {
			firstEntered, secondEntered := make(chan struct{}), make(chan struct{})
			firstRelease, secondRelease := make(chan struct{}), make(chan struct{})
			var firstOnce, secondOnce sync.Once
			releaseFirst := func() { firstOnce.Do(func() { close(firstRelease) }) }
			releaseSecond := func() { secondOnce.Do(func() { close(secondRelease) }) }
			var hits atomic.Int32
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if hits.Add(1) == 1 {
					close(firstEntered)
					<-firstRelease
				} else {
					close(secondEntered)
					<-secondRelease
				}
				w.Header().Set("X-Roami-Model-Admission-Ms", "999999")
				w.Header().Set("Content-Type", "text/event-stream")
				body := billableEvents
				if catalog {
					body = "event: response.completed\ndata: {\"type\":\"response.completed\",\"response\":{\"usage\":{\"input_tokens\":1000000,\"output_tokens\":125000}}}\n\n"
				}
				_, _ = io.WriteString(w, body)
			}))
			defer upstream.Close()
			defer releaseFirst()
			defer releaseSecond()
			var handler *Handler
			if catalog {
				handler = catalogHandler(t, upstream.URL+"/v1", "openai-responses")
			} else {
				handler = nodeConfiguredHandler(t, newLedger(t), upstream.URL)
			}
			if err := handler.Ledger.Configure(testConfiguration(floatPointer(10))); err != nil {
				t.Fatal(err)
			}
			perform := func(w *httptest.ResponseRecorder) {
				if !catalog {
					handler.ServeHTTP(w, modelRequest(upstream.URL))
					return
				}
				request := httptest.NewRequest("POST", "/v1/responses", strings.NewReader(`{"model":"coding-main","input":"synthetic timing control","stream":true}`))
				request.Header.Set("Authorization", "Bearer "+handler.Catalog.credential("codex"))
				handler.publicModels(w, request)
			}
			first, second := httptest.NewRecorder(), httptest.NewRecorder()
			firstDone, secondDone := make(chan struct{}), make(chan struct{})
			secondStarted := false
			go func() { defer close(firstDone); perform(first) }()
			defer func() {
				releaseFirst()
				releaseSecond()
				awaitAdmission(t, firstDone)
				if secondStarted {
					awaitAdmission(t, secondDone)
				}
			}()
			awaitAdmission(t, firstEntered)
			go func() { defer close(secondDone); perform(second) }()
			secondStarted = true
			awaitAdmissionQueue(t, handler, 1)
			time.Sleep(20 * time.Millisecond)
			releaseFirst()
			awaitAdmission(t, secondEntered)
			header := second.Header().Get("X-Roami-Model-Admission-Ms")
			elapsed, err := strconv.ParseInt(header, 10, 64)
			if err != nil || elapsed < 20 {
				t.Fatalf("queued admission duration missing: %q %v", header, err)
			}
			time.Sleep(20 * time.Millisecond)
			if second.Header().Get("X-Roami-Model-Admission-Ms") != header {
				t.Fatal("upstream wait changed the completed admission measurement")
			}
			releaseSecond()
			awaitAdmission(t, firstDone)
			awaitAdmission(t, secondDone)
			if first.Code != 200 || second.Code != 200 || second.Header().Get("X-Roami-Model-Admission-Ms") != header {
				t.Fatalf("upstream replaced admission receipt: first=%d second=%d header=%q", first.Code, second.Code, second.Header().Get("X-Roami-Model-Admission-Ms"))
			}
			stats, err := handler.Ledger.Statistics(1)
			if err != nil || len(stats.Recent) != 2 || hits.Load() != 2 {
				t.Fatalf("timing altered model calls: hits=%d rows=%d err=%v", hits.Load(), len(stats.Recent), err)
			}
		})
	}
}
