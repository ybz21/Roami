package modelgateway

import (
	"context"
	"encoding/json"
	metadb "github.com/ybz21/Roami/internal/storage"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func keyAction(t *testing.T, h *Handler, kind, action string) *httptest.ResponseRecorder {
	t.Helper()
	row := h.Catalog.keyView(context.Background(), kind)
	body, _ := json.Marshal(map[string]string{"revision": h.Catalog.value.Revision, "configRevision": row.ConfigRevision})
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/keys/"+kind+"/"+action, strings.NewReader(string(body))))
	return w
}
func requestWithKey(h *Handler, key, path, body string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	method := "POST"
	if body == "" {
		method = "GET"
	}
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	r.Header.Set("Authorization", "Bearer "+key)
	r.Header.Set("X-Roami-Agent-Kind", "claude")
	r.Header.Set("X-Eval-Session-Id", "forged-session")
	h.publicModels(w, r)
	return w
}
func TestAgentKeyRotationNativeConfigAndImmutableBilling(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer upstream-secret" || r.Header.Get("X-Roami-Agent-Kind") != "" || r.Header.Get("X-Eval-Session-Id") != "" {
			t.Error("upstream credential or attribution isolation failed")
		}
		_, _ = io.WriteString(w, `{"usage":{"prompt_tokens":1000000,"completion_tokens":0}}`)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL, "openai-completions")
	s := h.Catalog
	cfg := testConfiguration(nil)
	cfg.Pricing.Models["work/fixture"] = ModelPricing{InputPerMillion: 3}
	_ = h.Ledger.Configure(cfg)
	old, other := s.credential("opencode"), s.credential("claude")
	view, _ := s.agents.View(context.Background(), "opencode")
	body, _ := json.Marshal(map[string]string{"kind": "opencode", "model": "coding-main", "revision": view.Revision, "catalogRevision": s.value.Revision})
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/apply", strings.NewReader(string(body))))
	if w.Code != 200 {
		t.Fatalf("apply %d %s", w.Code, w.Body)
	}
	payload := `{"model":"coding-main","messages":[{"role":"user","content":"fixture"}]}`
	if w = requestWithKey(h, old, "/v1/chat/completions", payload); w.Code != 200 {
		t.Fatalf("inference %d %s", w.Code, w.Body)
	}
	if w = keyAction(t, h, "opencode", "rotate"); w.Code != 200 {
		t.Fatalf("rotate %d %s", w.Code, w.Body)
	}
	key := s.credential("opencode")
	if key == old || s.credential("claude") != other {
		t.Fatal("rotation changed wrong agent")
	}
	native, _ := os.ReadFile(os.Getenv("OPENCODE_CONFIG"))
	if !strings.Contains(string(native), key) || strings.Contains(string(native), "upstream-secret") {
		t.Fatal("native key was not updated safely")
	}
	cfg.Pricing.Models["work/fixture"] = ModelPricing{InputPerMillion: 9}
	_ = h.Ledger.Configure(cfg)
	if w = requestWithKey(h, key, "/v1/chat/completions", payload); w.Code != 200 {
		t.Fatalf("rotated inference %d %s", w.Code, w.Body)
	}
	stats, err := h.Ledger.StatisticsForSource(1, "", "", "opencode")
	if err != nil || len(stats.Recent) != 2 || len(stats.Groups) != 1 || stats.Groups[0].Cost != "12.000000000" {
		t.Fatalf("billing %+v %v", stats, err)
	}
	ids := map[string]bool{}
	for _, call := range stats.Recent {
		ids[call.KeyID] = true
		if call.AgentKind != "opencode" || call.SourceID != "work" || call.RouteID != "coding-main" || call.Session != "" {
			t.Fatalf("wrong attribution %+v", call)
		}
	}
	if len(ids) != 2 {
		t.Fatal("key versions were lost")
	}
	if kind, _ := s.authenticate(old); kind != "opencode" {
		t.Fatal("old key lost during grace")
	}
	now := h.Ledger.now()
	h.Ledger.now = func() time.Time { return now.Add(6 * time.Minute) }
	if kind, _ := s.authenticate(old); kind != "" {
		t.Fatal("old key outlived grace")
	}
	if w = keyAction(t, h, "opencode", "disable"); w.Code != 200 {
		t.Fatal(w.Body)
	}
	if w = requestWithKey(h, key, "/v1/models", ""); w.Code != 401 {
		t.Fatal("disabled key accepted")
	}
	if w = requestWithKey(h, other, "/v1/models", ""); w.Code != 200 {
		t.Fatal("other agent was disabled")
	}
	if w = keyAction(t, h, "opencode", "rotate"); w.Code != 200 {
		t.Fatalf("reenable %s", w.Body)
	}
	if kind, _ := s.authenticate(key); kind != "" {
		t.Fatal("disabled old key revived")
	}
	persisted, err := openCatalog(h.Ledger)
	if err != nil || persisted.credential("opencode") != s.credential("opencode") {
		t.Fatal("key did not survive restart")
	}
}
func TestAgentKeySummaryPrivateAndRevisionProtected(t *testing.T) {
	h := catalogHandler(t, "https://upstream.example", "openai-responses")
	s := h.Catalog
	old := s.credential("codex")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/v1/model-gateway/keys", nil))
	var result struct {
		Data struct {
			Keys []agentKeyView `json:"keys"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &result)
	if w.Code != 200 || len(result.Data.Keys) != 5 || strings.Contains(w.Body.String(), old) || strings.Contains(w.Body.String(), s.value.Token) {
		t.Fatal("key summary leaked secrets or invented identities")
	}
	if w = requestWithKey(h, old, "/v1/model-gateway/keys", ""); w.Code != 404 {
		t.Fatal("private key management exposed")
	}
	w = httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/keys/codex/rotate", strings.NewReader(`{"revision":"stale","configRevision":"stale"}`)))
	if w.Code != 409 || s.credential("codex") != old {
		t.Fatal("stale rotation changed credential")
	}
	w = httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/v1/model-gateway/usage?agentKind=made-up", nil))
	if w.Code != 400 {
		t.Fatal("invented agent accepted")
	}
}
func TestPendingRotationSurvivesRestartAndCanFinish(t *testing.T) {
	h := catalogHandler(t, "https://upstream.example", "openai-responses")
	s := h.Catalog
	old := s.credential("codex")
	next := s.snapshot()
	next.AgentKeys["codex"] = agentKeyState{ID: "crash-generation", PreviousUntil: 1<<63 - 1, Pending: true}
	if err := s.persist(next); err != nil {
		t.Fatal(err)
	}
	reopened, err := openCatalog(h.Ledger)
	if err != nil {
		t.Fatal(err)
	}
	reopened.baseURL = s.baseURL
	h.Catalog = reopened
	now := h.Ledger.now()
	h.Ledger.now = func() time.Time { return now.Add(24 * time.Hour) }
	if kind, _ := reopened.authenticate(old); kind != "codex" {
		t.Fatal("crash stranded native old key")
	}
	if !reopened.keyView(context.Background(), "codex").Pending {
		t.Fatal("pending rotation was shown as complete")
	}
	id := reopened.value.AgentKeys["codex"].ID
	if w := keyAction(t, h, "codex", "rotate"); w.Code != 200 {
		t.Fatalf("resume %s", w.Body)
	}
	if reopened.value.AgentKeys["codex"].Pending || reopened.value.AgentKeys["codex"].ID != id {
		t.Fatal("did not finish pending rotation")
	}
}
func TestUnpricedUsagePreservedAndExplicitFreePrice(t *testing.T) {
	l := newLedger(t)
	call, err := l.Admit("cli_opencode", "no-price", "", "", CallAttribution{AgentKind: "opencode", SourceID: "source", RouteID: "route"})
	if err != nil {
		t.Fatal(err)
	}
	if err = l.Settle(call, &Usage{Input: 123, Output: 9}, 200, "", false); err != nil {
		t.Fatal(err)
	}
	stats, _ := l.Statistics(1)
	record := stats.Recent[0]
	if record.State != "unknown" || record.Cost != nil || record.Input == nil || *record.Input != 123 || record.PriceStatus != "unpriced" {
		t.Fatalf("unpriced was treated as free %+v", record)
	}
	c := defaultConfiguration()
	c.Pricing.Models["source/no-price"] = ModelPricing{}
	_ = l.Configure(c)
	free, err := l.Admit("cli_opencode", "no-price", "", "", CallAttribution{AgentKind: "opencode", SourceID: "source"})
	if err != nil {
		t.Fatal(err)
	}
	_ = l.Settle(free, &Usage{Input: 100}, 200, "", false)
	if free.PriceStatus != "priced" {
		t.Fatal("explicit zero was treated as unpriced")
	}
}

func TestAttributionMigrationPreservesLegacyCharges(t *testing.T) {
	root := t.TempDir()
	paths, err := metadb.ResolvePaths(root, root)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = paths.Ensure(); err != nil {
		t.Fatal(err)
	}
	dbPath := filepath.Join(paths.Database, "models", "gateway.db")
	old, err := metadb.OpenManaged(paths, metadb.DatabaseDescriptor{ID: "model-gateway", Kind: "model-gateway", Owner: "go-model-gateway", Path: dbPath}, schema[:2], metadb.Options{})
	if err != nil {
		t.Fatal(err)
	}
	_, err = old.Exec(`INSERT INTO gateway_calls(id,day,timezone,role,model,session_id,request_id,started_ms,state,currency,price_json,cost_nano) VALUES('historic','2026-10-29','UTC','cli_opencode','original-model','','original-request',1,'known','CNY','{}',123456789)`)
	if err != nil {
		t.Fatal(err)
	}
	_ = metadb.Discard(dbPath)
	l, err := Open(paths)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = metadb.Discard(dbPath) })
	var kind, key, model, request, status string
	var cost int64
	err = l.db.QueryRow(`SELECT agent_kind,key_id,model,request_id,price_status,cost_nano FROM gateway_calls WHERE id='historic'`).Scan(&kind, &key, &model, &request, &status, &cost)
	if err != nil || kind != "opencode" || key != "legacy" || model != "original-model" || request != "original-request" || status != "priced" || cost != 123456789 {
		t.Fatal("migration rewrote historical financial evidence", err)
	}
}

func TestRevocationRejectsQueuedRequestBeforeItReachesUpstream(t *testing.T) {
	entered, release := make(chan struct{}), make(chan struct{})
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(entered)
		<-release
		_, _ = io.WriteString(w, `{"usage":{"prompt_tokens":1,"completion_tokens":1}}`)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL, "openai-completions")
	limit := 100.0
	_ = h.Ledger.Configure(testConfiguration(&limit))
	key := h.Catalog.credential("opencode")
	body := `{"model":"coding-main","messages":[{"role":"user","content":"fixture"}]}`
	first := make(chan *httptest.ResponseRecorder, 1)
	go func() { first <- requestWithKey(h, key, "/v1/chat/completions", body) }()
	<-entered
	queued := make(chan *httptest.ResponseRecorder, 1)
	go func() { queued <- requestWithKey(h, key, "/v1/chat/completions", body) }()
	deadline := time.Now().Add(time.Second)
	waiting := false
	for time.Now().Before(deadline) {
		h.mu.Lock()
		waiting = h.admissionChanged != nil
		h.mu.Unlock()
		if waiting {
			break
		}
		time.Sleep(time.Millisecond)
	}
	if !waiting {
		close(release)
		t.Fatal("second request did not wait on admission")
	}
	if w := keyAction(t, h, "opencode", "disable"); w.Code != 200 {
		close(release)
		t.Fatal(w.Body)
	}
	select {
	case w := <-queued:
		if w.Code != 401 {
			close(release)
			t.Fatalf("queued request was not revoked: %d", w.Code)
		}
	case <-time.After(time.Second):
		close(release)
		t.Fatal("revocation did not wake admission")
	}
	close(release)
	if w := <-first; w.Code != 200 {
		t.Fatalf("admitted call was interrupted: %d", w.Code)
	}
}
