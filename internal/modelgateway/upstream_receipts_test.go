package modelgateway

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	metadb "github.com/ybz21/Roami/internal/storage"
)

func TestUpstreamResponseReceiptEndToEnd(t *testing.T) {
	for _, mode := range []string{"node", "catalog", "bridge"} {
		for _, status := range []int{200, 401, 429, 500} {
			t.Run(fmt.Sprintf("%s/%d", mode, status), func(t *testing.T) {
				upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					w.Header().Set("X-Request-Id", "upstream-correlation")
					w.Header().Set("X-Roami-Model-Error", "MODEL_PROXY_DAILY_LIMIT")
					w.Header().Set("X-Roami-Model-Call", "forged-call")
					w.Header().Set("X-Roami-Private", "private-header")
					w.Header().Set("Content-Type", "application/json")
					if status == 429 {
						w.Header().Set("Retry-After", "3")
					}
					w.WriteHeader(status)
					if status == 200 {
						_ = json.NewEncoder(w).Encode(fixtureProtocolResponse("openai-completions"))
					} else {
						_, _ = io.WriteString(w, `{"error":{"message":"PRIVATE_ERROR_BODY"}}`)
					}
				}))
				defer upstream.Close()
				var h *Handler
				var response *httptest.ResponseRecorder
				if mode == "node" {
					h = nodeConfiguredHandler(t, newLedger(t), upstream.URL)
					r := modelRequest(upstream.URL)
					r.Header.Set("X-Request-Id", "client-correlation")
					response = httptest.NewRecorder()
					h.ServeHTTP(response, r)
				} else {
					h = catalogHandler(t, upstream.URL+"/v1", "openai-completions")
					protocol, path, agent := "openai-completions", "/v1/chat/completions", "roami"
					if mode == "bridge" {
						protocol, path, agent = "anthropic-messages", "/v1/messages", "claude"
					}
					body, _ := json.Marshal(protocolFixtureRequest(protocol, false))
					r := httptest.NewRequest("POST", path, strings.NewReader(string(body)))
					r.Header.Set("Authorization", "Bearer "+h.Catalog.credential(agent))
					r.Header.Set("X-Request-Id", "client-correlation")
					response = httptest.NewRecorder()
					h.publicModels(response, r)
				}
				if response.Header().Get("X-Roami-Model-Error") != "" || response.Header().Get("X-Roami-Private") != "" {
					t.Error("upstream impersonated private gateway response headers")
				}
				if response.Code != status || status == 429 && response.Header().Get("Retry-After") != "3" {
					t.Errorf("upstream status/retry semantics changed: upstream=%d downstream=%d", status, response.Code)
				}
				stats, err := h.Ledger.Statistics(1)
				if err != nil || len(stats.Recent) != 1 {
					t.Fatalf("ledger: %v %+v", err, stats.Recent)
				}
				record := stats.Recent[0]
				raw, _ := json.Marshal(record)
				var receipt map[string]any
				_ = json.Unmarshal(raw, &receipt)
				if receipt["upstreamHttpStatus"] != float64(status) || receipt["upstreamRequestId"] != "upstream-correlation" || record.Request != "client-correlation" {
					t.Errorf("upstream/client receipt lost: %s", raw)
				}
				if response.Header().Get("X-Roami-Model-Call") != record.ID || strings.Contains(string(raw), "PRIVATE_ERROR_BODY") || strings.Contains(string(raw), "private-header") {
					t.Error("receipt identity or private content boundary lost")
				}
				if record.Status != status {
					t.Errorf("existing settlement status changed: %d", record.Status)
				}
				api := httptest.NewRecorder()
				h.ServeHTTP(api, httptest.NewRequest("GET", "/v1/model-gateway/usage?days=1", nil))
				if api.Code != 200 || !strings.Contains(api.Body.String(), `"upstreamRequestId":"upstream-correlation"`) {
					t.Error("private statistics API lost the persisted receipt")
				}
			})
		}
	}
}

func TestUpstreamResponseReceiptMigration(t *testing.T) {
	root := t.TempDir()
	paths, err := metadb.ResolvePaths(root, root)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = paths.Ensure(); err != nil {
		t.Fatal(err)
	}
	dbPath := filepath.Join(paths.Database, "models", "gateway.db")
	old, err := metadb.OpenManaged(paths, metadb.DatabaseDescriptor{ID: "model-gateway", Kind: "model-gateway", Owner: "go-model-gateway", Path: dbPath}, schema[:3], metadb.Options{})
	if err != nil {
		t.Fatal(err)
	}
	_, err = old.Exec(`INSERT INTO gateway_calls(id,day,timezone,role,model,session_id,request_id,started_ms,state,currency,price_json,cost_nano,http_status,error_code) VALUES('old','2026-10-29','UTC','main','fixture','rsi-old','client-old',1,'unknown','CNY','{}',NULL,401,'MODEL_HTTP_401')`)
	if err != nil {
		t.Fatal(err)
	}
	if err = metadb.Discard(dbPath); err != nil {
		t.Fatal(err)
	}
	l, err := Open(paths)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = metadb.Discard(dbPath) })
	var state, code, request, upstream string
	var cost *int64
	var status, upstreamStatus int
	if err = l.db.QueryRow(`SELECT state,cost_nano,http_status,error_code,request_id,upstream_request_id,upstream_http_status FROM gateway_calls WHERE id='old'`).Scan(&state, &cost, &status, &code, &request, &upstream, &upstreamStatus); err != nil {
		t.Fatalf("new receipt columns unavailable: %v", err)
	}
	if state != "unknown" || cost != nil || status != 401 || code != "MODEL_HTTP_401" || request != "client-old" || upstream != "" || upstreamStatus != 0 {
		t.Fatal("migration invented a receipt or changed historical accounting")
	}
}

func TestUpstreamResponseReceiptHeaderSelection(t *testing.T) {
	raw, err := os.ReadFile("testdata/upstream-receipts.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct{ Name, Primary, Secondary, Expected string }
	if err = json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	for _, row := range cases {
		t.Run(row.Name, func(t *testing.T) {
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(401)
			}))
			defer upstream.Close()
			l := newLedger(t)
			h := nodeConfiguredHandler(t, l, upstream.URL)
			h.Client.Transport = receiptFixtureTransport{row.Primary, row.Secondary}
			h.ServeHTTP(httptest.NewRecorder(), modelRequest(upstream.URL))
			var actual string
			if err := l.db.QueryRow("SELECT upstream_request_id FROM gateway_calls").Scan(&actual); err != nil || actual != row.Expected {
				t.Errorf("receipt %q, want %q: %v", actual, row.Expected, err)
			}
		})
	}
}

type receiptFixtureTransport struct{ primary, secondary string }

func (r receiptFixtureTransport) RoundTrip(*http.Request) (*http.Response, error) {
	h := http.Header{}
	h.Set("X-Request-Id", r.primary)
	h.Set("Request-Id", r.secondary)
	return &http.Response{StatusCode: 401, Header: h, Body: io.NopCloser(strings.NewReader("{}"))}, nil
}

func TestUpstreamResponseReceiptConversionFailure(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Request-Id", "conversion-source")
		_, _ = io.WriteString(w, "invalid private response")
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL+"/v1", "openai-completions")
	body, _ := json.Marshal(protocolFixtureRequest("anthropic-messages", false))
	r := httptest.NewRequest("POST", "/v1/messages", strings.NewReader(string(body)))
	r.Header.Set("Authorization", "Bearer "+h.Catalog.credential("claude"))
	h.publicModels(httptest.NewRecorder(), r)
	stats, err := h.Ledger.Statistics(1)
	if err != nil || len(stats.Recent) != 1 {
		t.Fatal("missing conversion failure receipt", err)
	}
	record := stats.Recent[0]
	if record.Status != 502 || record.UpstreamStatus != 200 || record.UpstreamRequest != "conversion-source" {
		t.Fatalf("upstream response confused with conversion error: %+v", record)
	}
}

func TestUpstreamResponseReceiptNoResponse(t *testing.T) {
	l := newLedger(t)
	h := nodeConfiguredHandler(t, l, "http://127.0.0.1:1")
	h.Client.Transport = receiptConnectionFailure{}
	h.ServeHTTP(httptest.NewRecorder(), modelRequest("http://127.0.0.1:1"))
	stats, err := l.Statistics(1)
	if err != nil || len(stats.Recent) != 1 {
		t.Fatal("missing no-response receipt", err)
	}
	r := stats.Recent[0]
	if r.UpstreamStatus != 0 || r.UpstreamRequest != "" || r.Status != 0 || r.Error != "MODEL_TRANSPORT_FAILED" || r.State != "failed" {
		t.Fatalf("invented upstream receipt or changed settlement: %+v", r)
	}
}

type receiptConnectionFailure struct{}

func (receiptConnectionFailure) RoundTrip(*http.Request) (*http.Response, error) {
	return nil, &net.OpError{Op: "dial", Net: "tcp", Err: errors.New("private connection detail")}
}

func TestUpstreamResponseReceiptSettlementOnce(t *testing.T) {
	l := newLedger(t)
	if err := l.Configure(testConfiguration(nil)); err != nil {
		t.Fatal(err)
	}
	call, err := l.Admit("main", "fixture", "rsi-fixture", "client-request")
	if err != nil {
		t.Fatal(err)
	}
	call.upstream = upstreamReceipt{status: 200, request: "first-response"}
	if err = l.Settle(call, &Usage{Input: 100, Output: 7}, 200, "", false); err != nil {
		t.Fatal(err)
	}
	call.upstream = upstreamReceipt{status: 401, request: "late-response"}
	if err = l.Settle(call, nil, 401, "MODEL_HTTP_401", false); err != nil {
		t.Fatal(err)
	}
	stats, err := l.Statistics(1)
	if err != nil || len(stats.Recent) != 1 {
		t.Fatal("missing settled receipt", err)
	}
	r := stats.Recent[0]
	if r.UpstreamStatus != 200 || r.UpstreamRequest != "first-response" || r.Status != 200 || r.Request != "client-request" || r.State != "known" {
		t.Fatalf("late settlement overwrote the receipt: %+v", r)
	}
}
