package modelgateway

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

func discoverRequest(h *Handler, source ModelSource, revision string) *httptest.ResponseRecorder {
	body, _ := json.Marshal(map[string]any{"source": source, "revision": revision})
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/discover", strings.NewReader(string(body))))
	return w
}

func TestDiscoverDraftIsReadOnlyAndPaginatesAllModels(t *testing.T) {
	hits := atomic.Int32{}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		if r.URL.Path != "/v1/models" || r.Header.Get("x-api-key") != "draft-key" {
			t.Error("wrong endpoint or credentials")
		}
		if r.URL.Query().Get("after_id") == "first" {
			_, _ = io.WriteString(w, `{"data":[{"id":"second"},{"id":"first"},{"id":"draft-key"}],"has_more":false}`)
		} else {
			_, _ = io.WriteString(w, `{"data":[{"id":"first"}],"has_more":true,"last_id":"first"}`)
		}
	}))
	defer upstream.Close()
	h := catalogHandler(t, "https://saved.example/v1", "openai-completions")
	before := h.Catalog.snapshot()
	source := ModelSource{ID: "new-source", BaseURL: upstream.URL, Protocol: "anthropic-messages", AuthMode: "api_key", APIKey: "draft-key"}
	w := discoverRequest(h, source, before.Revision)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"models":["first","second"]`) || strings.Contains(w.Body.String(), "draft-key") || hits.Load() != 2 {
		t.Fatalf("discovery: %d %s (%d requests)", w.Code, w.Body, hits.Load())
	}
	after := h.Catalog.snapshot()
	if after.Revision != before.Revision || len(after.Sources) != 1 || len(after.Models) != 1 {
		t.Fatal("discovery wrote configuration")
	}
}

func TestDiscoverDraftReusesKeyOnlyAtSavedEndpoint(t *testing.T) {
	hits := atomic.Int32{}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		if r.Header.Get("Authorization") != "Bearer upstream-secret" {
			t.Error("saved key not reused")
		}
		_, _ = io.WriteString(w, `{"data":[{"id":"new-model"}]}`)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL, "openai-responses")
	view := h.Catalog.view(context.Background())
	source := view.Sources[0]
	w := discoverRequest(h, source, view.Revision)
	if w.Code != 200 || strings.Contains(w.Body.String(), "upstream-secret") {
		t.Fatalf("saved discovery: %d %s", w.Code, w.Body)
	}
	source.BaseURL += "/other"
	w = discoverRequest(h, source, view.Revision)
	if w.Code != 400 || !strings.Contains(w.Body.String(), "MODEL_KEY_REQUIRED_FOR_ENDPOINT") || hits.Load() != 1 {
		t.Fatal("saved key could be sent to a changed endpoint")
	}
}

func TestDiscoverDraftRejectsInvalidAndStaleInputBeforeConnecting(t *testing.T) {
	h := catalogHandler(t, "https://saved.example/v1", "openai-responses")
	source := h.Catalog.view(context.Background()).Sources[0]
	for _, endpoint := range []string{"http://external.example/v1", "https://user:pass@external.example/v1", "https://external.example/v1?key=secret", h.Catalog.baseURL, "file:///tmp/models"} {
		source.BaseURL = endpoint
		if w := discoverRequest(h, source, h.Catalog.value.Revision); w.Code != 400 {
			t.Fatalf("invalid endpoint accepted: %s", endpoint)
		}
	}
	if w := discoverRequest(h, source, "stale"); w.Code != 409 {
		t.Fatal("stale revision accepted")
	}
}

func TestDiscoverDraftDiscardsResultIfCatalogChanges(t *testing.T) {
	var h *Handler
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h.Catalog.mu.Lock()
		next := h.Catalog.snapshot()
		err := h.Catalog.update(context.Background(), next)
		h.Catalog.mu.Unlock()
		if err != nil {
			t.Error(err)
		}
		_, _ = io.WriteString(w, `{"data":[{"id":"obsolete"}]}`)
	}))
	defer upstream.Close()
	h = catalogHandler(t, upstream.URL, "openai-completions")
	w := discoverRequest(h, h.Catalog.view(context.Background()).Sources[0], h.Catalog.value.Revision)
	if w.Code != 409 || strings.Contains(w.Body.String(), "obsolete") {
		t.Fatalf("stale result: %d %s", w.Code, w.Body)
	}
}

func TestCatalogAcceptsFullDiscoveredDirectory(t *testing.T) {
	h := catalogHandler(t, "https://saved.example/v1", "openai-completions")
	next := h.Catalog.snapshot()
	next.Models = nil
	for i := 0; i < 1000; i++ {
		id := fmt.Sprintf("model-%d", i)
		next.Models = append(next.Models, CatalogModel{ID: id, Name: id, Protocol: "openai-completions", Strategy: "fixed", Candidates: []ModelCandidate{{SourceID: "work", Model: id}}})
	}
	if err := h.Catalog.update(context.Background(), next); err != nil {
		t.Fatalf("full directory rejected: %v", err)
	}
}

func TestCatalogAllowsPrivateHTTPModelSources(t *testing.T) {
	h := catalogHandler(t, "https://saved.example/v1", "openai-completions")
	source := h.Catalog.view(context.Background()).Sources[0]
	for _, endpoint := range []string{"http://192.168.120.56:3425/v1", "http://10.0.0.1/v1", "http://172.16.0.1/v1", "http://[fd00::1]/v1"} {
		source.BaseURL = endpoint
		if _, err := h.Catalog.validatedSource(source, ModelSource{}); err != nil {
			t.Errorf("private endpoint %s: %v", endpoint, err)
		}
	}
}

func TestDiscoverRetainsAdvertisedCapabilitiesAndUnknowns(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, `{"data":[{"id":"vendor/free","name":"Free model","context_length":131072,"top_provider":{"max_completion_tokens":8192},"architecture":{"input_modalities":["text","image"],"output_modalities":["text"]},"supported_parameters":["tools","reasoning"],"pricing":{"prompt":"0","completion":"0"}},{"id":"vendor/unknown"},{"id":"vendor/paid","pricing":{"prompt":"0.000001","completion":"0.000003"}}]}`)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL, "openai-completions")
	before := h.Catalog.snapshot()
	w := discoverRequest(h, before.Sources[0], before.Revision)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	var result struct {
		Data struct {
			Details []struct {
				ID                      string
				Context, Output         int
				Tools, Reasoning        *bool
				InputPrice, OutputPrice *float64
				InputModalities         []string
			}
		}
	}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	rows := result.Data.Details
	if len(rows) != 3 || rows[0].Context != 131072 || rows[0].Output != 8192 || rows[0].Tools == nil || !*rows[0].Tools || rows[0].Reasoning == nil || !*rows[0].Reasoning || len(rows[0].InputModalities) != 2 || rows[0].InputPrice == nil || *rows[0].InputPrice != 0 {
		t.Fatalf("metadata lost: %s", w.Body.String())
	}
	if rows[1].InputPrice == nil || *rows[1].InputPrice != 1 || *rows[1].OutputPrice != 3 || rows[2].Tools != nil || rows[2].InputPrice != nil {
		t.Fatalf("unknowns or unit conversion incorrect: %s", w.Body.String())
	}
	if h.Catalog.value.Revision != before.Revision {
		t.Fatal("read changed catalog")
	}
}
