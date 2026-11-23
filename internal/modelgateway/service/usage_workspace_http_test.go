package service

import (
	"encoding/json"
	"net/http/httptest"
	"testing"

	"github.com/ybz21/Roami/internal/modelgateway/accounting"
)

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
	var result struct{ Data accounting.WorkspaceUsage }
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil || w.Code != 200 || result.Data.From != "2026-10-01" || result.Data.To != "2026-10-03" || result.Data.Days != 3 {
		t.Fatalf("custom range: %d %s %v", w.Code, w.Body, err)
	}
}
