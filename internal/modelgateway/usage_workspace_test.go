package modelgateway

import (
	"encoding/json"
	metadb "github.com/ybz21/Roami/internal/storage"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"testing"
	"time"
)

func TestWorkspaceSourceAttributionSurvivesCompaction(t *testing.T) {
	l := newLedger(t)
	if err := l.Configure(testConfiguration(nil)); err != nil {
		t.Fatal(err)
	}
	for _, source := range []string{"a", "b", ""} {
		call, err := l.Admit("main", "fixture", "", "", CallAttribution{AgentKind: "roami", SourceID: source})
		if err != nil {
			t.Fatal(err)
		}
		if err = l.Settle(call, &Usage{Input: 100, Output: 20, Cached: 30}, 200, "", false); err != nil {
			t.Fatal(err)
		}
	}
	before, err := l.WorkspaceUsage(UsageQuery{View: "overview", Days: 7, Page: 1, SourceID: "a"})
	if err != nil || len(before.Groups) != 1 || before.Groups[0].Requests != 1 || len(before.Today) != 3 {
		t.Fatalf("filtered groups/global today: %+v %v", before, err)
	}
	now := l.now().Add(49 * time.Hour)
	l.now = func() time.Time { return now }
	if err = l.Compact(); err != nil {
		t.Fatal(err)
	}
	after, err := l.WorkspaceUsage(UsageQuery{View: "overview", Days: 7, Page: 1, SourceID: "a"})
	if err != nil || len(after.Groups) != 1 || after.Groups[0].SourceID != "a" || after.Groups[0].Cost != before.Groups[0].Cost || after.Archived != 1 {
		t.Fatalf("lost attribution after compaction: %+v %v", after, err)
	}
	audit, err := l.WorkspaceUsage(UsageQuery{View: "audit", Days: 7, Page: 1, SourceID: "a"})
	if err != nil || audit.Total != 0 || len(audit.Recent) != 0 || audit.Archived != 1 {
		t.Fatalf("archived records fabricated: %+v %v", audit, err)
	}
	unknown, err := l.WorkspaceUsage(UsageQuery{View: "overview", Days: 7, Page: 1, MissingSource: true})
	if err != nil || len(unknown.Groups) != 1 || unknown.Groups[0].SourceID != "" || unknown.Groups[0].Requests != 1 {
		t.Fatalf("unattributed source merged incorrectly: %+v %v", unknown, err)
	}
}

func TestWorkspaceAuditPaginationSearchAndFrozenPrice(t *testing.T) {
	l := newLedger(t)
	if err := l.Configure(testConfiguration(nil)); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 45; i++ {
		call, err := l.Admit("main", "fixture", "", "client_%quoted'", CallAttribution{AgentKind: "codex", SourceID: "a"})
		if err != nil {
			t.Fatal(err)
		}
		if err = l.Settle(call, &Usage{Input: 100, Output: 2, Cached: 50}, 200, "", false); err != nil {
			t.Fatal(err)
		}
	}
	changed := testConfiguration(nil)
	changed.Pricing.Models["fixture"] = ModelPricing{InputPerMillion: 90}
	if err := l.Configure(changed); err != nil {
		t.Fatal(err)
	}
	read := func(query string) WorkspaceUsage {
		t.Helper()
		v, _ := url.ParseQuery("view=audit&days=7&" + query)
		q, err := workspaceQuery(v)
		if err != nil {
			t.Fatal(err)
		}
		result, err := l.WorkspaceUsage(q)
		if err != nil {
			t.Fatal(err)
		}
		return result
	}
	first := read("page=1")
	second := read("page=2")
	last := read("page=3")
	if first.Total != 45 || len(first.Recent) != 20 || len(second.Recent) != 20 || len(last.Recent) != 5 {
		t.Fatalf("wrong pagination: %d %d %d %d", first.Total, len(first.Recent), len(second.Recent), len(last.Recent))
	}
	seen := map[string]bool{}
	for _, page := range []WorkspaceUsage{first, second, last} {
		for _, r := range page.Recent {
			if seen[r.ID] {
				t.Fatalf("duplicate request %s", r.ID)
			}
			seen[r.ID] = true
			if r.Price == nil || r.Price.InputPerMillion != 2 || r.Input == nil || *r.Input != 100 || r.Finished == nil {
				t.Fatalf("receipt/price snapshot changed: %+v", r)
			}
		}
	}
	if page := read("page=999"); page.Page != 3 || len(page.Recent) != 5 {
		t.Fatalf("out of range page not clamped: %+v", page)
	}
	if result := read("q=" + url.QueryEscape("%quoted'")); result.Total != 45 {
		t.Fatalf("search interpreted SQL symbols: %d", result.Total)
	}
	if result := read("sourceId=b"); result.Total != 0 {
		t.Fatalf("source filter ignored: %d", result.Total)
	}
	missing, err := l.Admit("main", "unpriced", "", "missing", CallAttribution{AgentKind: "claude", SourceID: "b"})
	if err != nil {
		t.Fatal(err)
	}
	if err = l.Settle(missing, nil, 0, "MODEL_TRANSPORT_FAILED", false); err != nil {
		t.Fatal(err)
	}
	result := read("state=unknown&sourceId=b")
	if result.Total != 1 || result.Recent[0].Cost != nil || result.Recent[0].Input != nil || result.Recent[0].Price != nil {
		t.Fatalf("unknown receipt invented: %+v", result)
	}
}

func TestWorkspaceQueryValidatesRangeAndFilters(t *testing.T) {
	l := newLedger(t)
	h := NewHandler(l)
	for _, query := range []string{"view=wrong", "view=audit&page=0", "view=audit&page=abc", "view=audit&state=paid", "view=overview&source=OpenAI", "view=audit&unattributed=1&sourceId=a", "view=overview&start=2026-10-30&end=2026-10-29", "view=overview&start=2026-10-28", "view=overview&start=2026-02-30&end=2026-10-29"} {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("GET", "/v1/model-gateway/usage?"+query, nil))
		if w.Code != 400 {
			t.Fatalf("invalid query accepted: %s: %d %s", query, w.Code, w.Body)
		}
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/v1/model-gateway/usage?view=overview&start=2026-10-01&end=2026-10-03", nil))
	var result struct{ Data WorkspaceUsage }
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil || w.Code != 200 || result.Data.From != "2026-10-01" || result.Data.To != "2026-10-03" || result.Data.Days != 3 {
		t.Fatalf("custom range: %d %s %v", w.Code, w.Body, err)
	}
}

func TestDailySourceMigrationPreservesUnattributedHistory(t *testing.T) {
	root := t.TempDir()
	paths, err := metadb.ResolvePaths(root, root)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = paths.Ensure(); err != nil {
		t.Fatal(err)
	}
	old, err := metadb.OpenManaged(paths, metadb.DatabaseDescriptor{ID: "model-gateway", Kind: "model-gateway", Owner: "go-model-gateway", Path: filepath.Join(paths.Database, "models", "gateway.db")}, schema[:5], metadb.Options{})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = old.Exec(`INSERT INTO gateway_daily_usage VALUES('2026-10-20','UTC','main','fixture','CNY','roami','other',3,12,4,2,100,0,0,0)`); err != nil {
		t.Fatal(err)
	}
	if err = metadb.Discard(old.Path()); err != nil {
		t.Fatal(err)
	}
	l, err := Open(paths)
	if err != nil {
		t.Fatal(err)
	}
	defer metadb.Discard(l.db.Path())
	l.now = func() time.Time { return time.Date(2026, 10, 29, 0, 0, 0, 0, time.UTC) }
	result, err := l.WorkspaceUsage(UsageQuery{View: "overview", Days: 30, Page: 1, MissingSource: true})
	if err != nil || len(result.Groups) != 1 || result.Groups[0].Requests != 3 || result.Groups[0].SourceID != "" || result.Groups[0].Cost != "0.000000100" {
		t.Fatalf("migration changed old totals: %+v %v", result, err)
	}
}
