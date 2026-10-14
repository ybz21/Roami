package api

import (
	"context"
	"encoding/json"
	"github.com/gin-gonic/gin"
	"net/http/httptest"
	"testing"
	"ttmux-web/worktree"
)

func TestDayActivityValidatesRangeAndReturnsOnlySelectedDay(t *testing.T) {
	store := NewGitFootprintStore(t.TempDir())
	defer store.db.Close()
	if err := store.Import(context.Background(), []worktree.ActivityCommit{{OID: "start", At: 100, Repo: "/project", Subject: "Ship"}, {OID: "end", At: 200}}); err != nil {
		t.Fatal(err)
	}
	a := &API{GitFootprints: store}
	for _, tc := range []struct {
		query  string
		status int
	}{{"from=100&to=200", 200}, {"from=bad&to=200", 400}, {"from=200&to=100", 400}, {"from=0&to=999999", 400}} {
		w := httptest.NewRecorder()
		c, _ := gin.CreateTestContext(w)
		c.Request = httptest.NewRequest("GET", "/activity/day?"+tc.query, nil)
		a.DayActivity(c)
		if w.Code != tc.status {
			t.Fatalf("%s: %d", tc.query, w.Code)
		}
		if tc.status == 200 {
			var body struct {
				Data struct{ Commits []GitDayFootprint }
			}
			if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
				t.Fatal(err)
			}
			if len(body.Data.Commits) != 1 || body.Data.Commits[0].OID != "start" {
				t.Fatalf("unexpected day: %s", w.Body.String())
			}
		}
	}
}
