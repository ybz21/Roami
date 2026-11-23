package modelgateway

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/ybz21/Roami/internal/modelgateway/protocoltest"
)

func readBillingAudit(t *testing.T, h *Handler, id string) []requestAttemptDetail {
	t.Helper()
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/v1/model-gateway/monitor/requests/"+id, nil))
	var reply struct {
		Data struct {
			Request  MonitorRecord
			Attempts []requestAttemptDetail
		}
	}
	if err := json.Unmarshal(w.Body.Bytes(), &reply); err != nil || w.Code != 200 || reply.Data.Request.RequestID != id {
		t.Fatalf("audit = %d %s (%v)", w.Code, w.Body, err)
	}
	return reply.Data.Attempts
}

func TestRequestAttemptBillingMatchesCallAndServerObservation(t *testing.T) {
	l := newLedger(t)
	config := testConfiguration(nil)
	config.Currency = "USD"
	if err := l.Configure(config); err != nil {
		t.Fatal(err)
	}
	now := l.now()
	monitor, err := openMonitorStore(filepath.Join(t.TempDir(), "monitor.ring"), 20, func() time.Time { return now })
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = monitor.Close() })
	id := uuid.NewString()
	attribution := CallAttribution{AgentKind: "roami", SourceID: "source", RouteID: "route", ObservationRequestID: id}
	admit := func(attribution CallAttribution) Call {
		t.Helper()
		// Both matching and unrelated calls can carry the same caller-supplied X-Request-Id.
		call, err := l.Admit("main", "fixture", "session", id, attribution)
		if err != nil {
			t.Fatal(err)
		}
		return call
	}
	add := func(callID string, index int, source string) {
		t.Helper()
		if err := monitor.Append(MonitorRecord{RequestID: id, CallID: callID, Attempt: index,
			At: now.UnixMilli(), SourceID: source, RouteID: "route", Model: "fixture", Quality: "unchecked"}); err != nil {
			t.Fatal(err)
		}
	}
	settle := func(call Call, usage *Usage, notSent bool, providerID string) {
		t.Helper()
		call.upstream = upstreamReceipt{status: 200, request: providerID}
		if err := l.Settle(call, usage, 200, "", notSent); err != nil {
			t.Fatal(err)
		}
	}

	paid := admit(attribution)
	settle(paid, &Usage{Input: 10}, false, "up-paid")
	add(paid.ID, 1, "source")

	free := admit(attribution)
	settle(free, nil, true, "up-zero")
	// Historical accounting may carry a different currency; the response must preserve the per-call snapshot.
	if _, err := l.db.Exec("UPDATE gateway_calls SET currency='CNY' WHERE id=?", free.ID); err != nil {
		t.Fatal(err)
	}
	add(free.ID, 2, "source")

	pending := admit(attribution)
	add(pending.ID, 3, "source")

	unknown := admit(attribution)
	settle(unknown, nil, false, "up-unknown")
	add(unknown.ID, 4, "source")

	add("", 5, "source")
	add(uuid.NewString(), 6, "source")
	add(paid.ID, 7, "wrong-source") // An exact call ID cannot override the attempt's attribution.

	foreign := attribution
	foreign.ObservationRequestID = uuid.NewString()
	unrelated := admit(foreign)
	settle(unrelated, &Usage{Input: 19}, false, "up-other-request")
	add(unrelated.ID, 8, "source")

	legacy := attribution
	legacy.ObservationRequestID = ""
	historic := admit(legacy)
	settle(historic, &Usage{Input: 19}, false, "up-legacy")
	add(historic.ID, 9, "source")
	if err := monitor.Append(MonitorRecord{RequestID: id, At: now.UnixMilli(), Outcome: "recovered",
		RouteID: "route", Attempts: 9, Status: 200, Quality: "unchecked"}); err != nil {
		t.Fatal(err)
	}

	h := NewHandler(l)
	h.Monitor = monitor
	records := readBillingAudit(t, h, id)
	want := []string{"settled", "settled", "pending", "unknown", "unrecorded", "missing", "missing", "missing", "missing"}
	if len(records) != len(want) {
		t.Fatalf("attempt count = %d, want %d", len(records), len(want))
	}
	for i, expected := range want {
		got := records[i]
		if got.Attempt != i+1 || got.Billing.State != expected {
			t.Errorf("attempt %d billing = %+v, want %q", i+1, got, expected)
		}
		if expected != "settled" && got.Billing.Cost != nil {
			t.Errorf("attempt %d unexpectedly had a cost: %+v", i+1, got.Billing)
		}
		if expected == "missing" && got.Billing.UpstreamRequestID != "" {
			t.Errorf("attempt %d exposed an unverified receipt: %+v", i+1, got.Billing)
		}
	}
	if b := records[0].Billing; b.Currency != paid.Currency || b.Currency == "CNY" || b.Cost == nil || *b.Cost != "0.000020000" || b.UpstreamRequestID != "up-paid" {
		t.Errorf("paid billing = %+v", b)
	}
	if b := records[1].Billing; b.Currency != "CNY" || b.Cost == nil || *b.Cost != "0.000000000" || b.UpstreamRequestID != "up-zero" {
		t.Errorf("zero billing = %+v", b)
	}
	if b := records[3].Billing; b.UpstreamRequestID != "up-unknown" {
		t.Errorf("verified receipt lost while cost was unknown: %+v", b)
	}

	h.Ledger = nil
	if records = readBillingAudit(t, h, id); records[0].Billing.State != "unavailable" || records[4].Billing.State != "unrecorded" {
		t.Errorf("ledger absence made valid trace unavailable: %+v", records)
	}
}

func TestCatalogRequestAuditUsesServerObservationForBilling(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("X-Request-Id", "provider-audit")
		protocoltest.WriteResponse(w, "openai-completions", false)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL+"/v1", "openai-completions")
	if err := h.Ledger.Configure(testConfiguration(nil)); err != nil {
		t.Fatal(err)
	}
	monitor, err := openMonitorStore(filepath.Join(t.TempDir(), "monitor.ring"), 10, h.Ledger.now)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = monitor.Close() })
	h.Monitor = monitor
	body, err := json.Marshal(protocoltest.Request("openai-completions", false))
	if err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest("POST", "/v1/chat/completions", strings.NewReader(string(body)))
	r.Header.Set("Authorization", "Bearer "+h.Catalog.credential("roami"))
	r.Header.Set("X-Request-Id", "client-audit")
	w := httptest.NewRecorder()
	h.publicModels(w, r)
	id := w.Header().Get(requestHeader)
	if w.Code != 200 || id == "" || id == "client-audit" {
		t.Fatalf("request ended without a server observation: %d %s %v", w.Code, w.Body, w.Header())
	}
	audit := readBillingAudit(t, h, id)
	if len(audit) != 1 || audit[0].Billing.UpstreamRequestID != "provider-audit" || audit[0].Billing.State != "settled" {
		t.Fatalf("billing receipt not linked to server observation: %+v", audit)
	}
	var clientID string
	if err := h.Ledger.db.QueryRow("SELECT request_id FROM gateway_calls WHERE id=?", audit[0].CallID).Scan(&clientID); err != nil || clientID != "client-audit" {
		t.Fatalf("caller correlation changed: %q, %v", clientID, err)
	}
}
