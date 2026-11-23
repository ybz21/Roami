package modelgateway

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

func TestRouteProbeUsesAggregateFailoverAndReportsCooldown(t *testing.T) {
	for _, failBackup := range []bool{false, true} {
		t.Run(fmt.Sprintf("backupFailure=%t", failBackup), func(t *testing.T) {
			var primary, backup atomic.Int64
			h := aggregateFixture(t, func(w http.ResponseWriter, _ *http.Request) {
				primary.Add(1)
				http.Error(w, "upstream private error detail", http.StatusBadGateway)
			}, func(w http.ResponseWriter, _ *http.Request) {
				backup.Add(1)
				if failBackup {
					http.Error(w, "upstream private error detail", http.StatusBadGateway)
					return
				}
				w.Header().Set("Content-Type", "text/event-stream")
				fmt.Fprint(w, "data: {\"type\":\"response.output_text.delta\",\"output_index\":0,\"content_index\":0,\"delta\":\"2\"}\n\n",
					"data: {\"type\":\"response.completed\",\"response\":{\"id\":\"response-fixture\",\"status\":\"completed\",\"output\":[{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"2\"}]}],\"usage\":{\"input_tokens\":8,\"output_tokens\":1}}}\n\n")
			})
			catalog := h.Catalog.snapshot()
			catalog.Models[0].Strategy = "order"
			if err := h.Catalog.update(context.Background(), catalog); err != nil {
				t.Fatal(err)
			}
			check := func() routeProbeResult {
				t.Helper()
				w := httptest.NewRecorder()
				h.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/v1/model-gateway/monitor/check", strings.NewReader(`{"routeId":"coding-main","rule":"answer"}`)))
				var result struct{ Data routeProbeResult }
				if w.Code != http.StatusOK || json.Unmarshal(w.Body.Bytes(), &result) != nil || strings.Contains(w.Body.String(), "upstream private error detail") {
					t.Fatalf("probe response: %d %s", w.Code, w.Body)
				}
				return result.Data
			}
			result := check()
			if result.Attempts != 2 || result.SourceID != "backup" || result.UpstreamModel != "fixture" || primary.Load() != 1 || backup.Load() != 1 {
				t.Fatalf("probe did not exercise the route: %+v", result)
			}
			if !failBackup {
				if !result.Success || result.Status != http.StatusOK || result.UpstreamStatus != http.StatusOK || result.Error != "" {
					t.Fatalf("recovered probe: %+v", result)
				}
				return
			}
			if result.Success || result.Status != http.StatusServiceUnavailable || result.UpstreamStatus != http.StatusBadGateway || result.Error != "MODEL_ROUTE_NO_AVAILABLE_MEMBER" {
				t.Fatalf("exhausted probe: %+v", result)
			}
			if blocked := check(); blocked.Success || blocked.Status != http.StatusServiceUnavailable || blocked.Attempts != 0 || blocked.Blocks["cooldown"] != 2 || primary.Load() != 1 || backup.Load() != 1 {
				t.Fatalf("cooldown probe: %+v", blocked)
			}
		})
	}
}

func TestDirectoryReturnsConfiguredRoutesWhenAProviderDirectoryIsUnavailable(t *testing.T) {
	h := aggregateFixture(t, func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "directory unavailable", http.StatusServiceUnavailable)
	}, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"data":[{"id":"fixture"}]}`)
	})
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/v1/model-gateway/models?all=true&refresh=true", nil))
	var response struct {
		Data struct {
			Models          []ModelDirectoryRow
			RefreshFailures []string
		}
	}
	if w.Code != http.StatusOK || json.Unmarshal(w.Body.Bytes(), &response) != nil ||
		len(response.Data.RefreshFailures) != 1 || response.Data.RefreshFailures[0] != "work" ||
		len(response.Data.Models) < 1 || response.Data.Models[0].ID != "coding-main" || !response.Data.Models[0].Configured {
		t.Fatalf("directory response: %d %s", w.Code, w.Body)
	}
}

func TestRouteProbeRejectsUnknownOrAmbiguousRoute(t *testing.T) {
	h := aggregateFixture(t, responseFixture, responseFixture)
	for _, tc := range []struct {
		body string
		want int
	}{
		{`{"routeId":"missing","rule":"answer"}`, http.StatusNotFound},
		{`{"routeId":"coding-main","sourceId":"work","model":"fixture","rule":"answer"}`, http.StatusBadRequest},
	} {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/v1/model-gateway/monitor/check", strings.NewReader(tc.body)))
		if w.Code != tc.want {
			t.Errorf("probe %s = %d %s", tc.body, w.Code, w.Body)
		}
	}
}
