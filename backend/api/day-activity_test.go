package api

import (
	"context"
	"encoding/json"
	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/worktree"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestDayActivityValidatesRangeAndReturnsOnlySelectedDay(t *testing.T) {
	store := NewGitFootprintStore(t.TempDir())
	defer store.db.Close()
	if err := store.Import(context.Background(), []worktree.ActivityCommit{{OID: "start", At: 100, Repo: "/project", Subject: "Ship"}, {OID: "second", At: 120, Repo: "/project", Subject: "Private detail"}, {OID: "third", At: 150, Repo: "/other"}, {OID: "end", At: 200}}); err != nil {
		t.Fatal(err)
	}
	a := &API{GitFootprints: store, Footprints: &AIFootprintStore{events: []AIFootprint{{At: 100, Dialogues: 2}, {At: 150, Tasks: 1}, {At: 200, Dialogues: 7}}}}
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
			if strings.Contains(w.Body.String(), "Private detail") || strings.Contains(w.Body.String(), "subject") {
				t.Fatal("summary leaked individual details")
			}
			var body struct {
				Data struct {
					Commits   int
					Dialogues int
					Tasks     int
					Projects  []DayProjectCount
				}
			}
			if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
				t.Fatal(err)
			}
			if body.Data.Commits != 3 || len(body.Data.Projects) != 2 || body.Data.Projects[0].Repo != "/project" || body.Data.Projects[0].Count != 2 || body.Data.Dialogues != 2 || body.Data.Tasks != 1 {
				t.Fatalf("unexpected day: %s", w.Body.String())
			}
		}
	}
}
