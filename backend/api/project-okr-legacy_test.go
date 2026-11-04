package api

import (
	"database/sql"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/okr"
)

func legacyHistoryFixture(t *testing.T) (*API, string, string, *sql.DB) {
	t.Helper()
	a, _, id := projectOKRFixture(t)
	dir, _ := a.Projects.Dir(id)
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	setter, hasFileStore := any(a.ProjectOKR).(interface {
		SetProjects(func() map[string]string)
	})
	if hasFileStore {
		setter.SetProjects(nil)
	}
	var config okr.Config
	if err := json.Unmarshal([]byte(projectOKRConfigJSON()), &config); err != nil {
		t.Fatal(err)
	}
	config.Swarm = "old-group"
	if _, err := a.ProjectOKR.Save(id, config); err != nil {
		t.Fatal(err)
	}
	if hasFileStore {
		setter.SetProjects(func() map[string]string {
			result := map[string]string{}
			for id, entry := range a.Projects.Entries() {
				result[id] = entry.Dir
			}
			return result
		})
	}
	if _, err := a.Meta.Exec(`INSERT INTO swarms(id,name,goal,status,dir) VALUES('legacy-1','old-group','Preserved work','running',?)`, dir); err != nil {
		t.Fatal(err)
	}
	if _, err := a.Meta.Exec(`INSERT INTO swarm_members(swarm_id,name,task,done,kind,role) VALUES('legacy-1','writer','Claimed draft',1,'codex','member')`); err != nil {
		t.Fatal(err)
	}
	if _, err := a.Meta.Exec(`INSERT INTO swarm_cards(swarm_id,id,title,descr,col) VALUES('legacy-1','task-1','Claimed publication','Needs receipts','done')`); err != nil {
		t.Fatal(err)
	}
	groupPath := filepath.Join(filepath.Dir(a.Meta.Info().Path), "swarms", "legacy-1", "swarm.db")
	if err := os.MkdirAll(filepath.Dir(groupPath), 0700); err != nil {
		t.Fatal(err)
	}
	group, err := sql.Open("sqlite", groupPath)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = group.Close() })
	for _, statement := range []string{`PRAGMA journal_mode=WAL`, `PRAGMA wal_autocheckpoint=0`, `CREATE TABLE posts(id INTEGER PRIMARY KEY,ts TEXT,author TEXT,kind TEXT,re INTEGER,text TEXT)`, `CREATE TABLE members(name TEXT PRIMARY KEY,task TEXT)`, `CREATE TABLE cards(id TEXT PRIMARY KEY,title TEXT,col TEXT)`, `INSERT INTO posts VALUES(1,'2026-11-03 12:00:00','writer','note',NULL,'Draft only, no receipt')`, `INSERT INTO posts VALUES(2,'2026-11-03 12:01:00','reviewer','note',1,'Historical claim needs verification')`} {
		if _, err := group.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	return a, id, groupPath, group
}

func requestLegacyHistory(t *testing.T, a *API, id string) *legacySwarmHistory {
	t.Helper()
	router := gin.New()
	router.GET("/legacy/:key", a.ProjectOKRLegacySwarm)
	response := projectOKRRequest(t, router, "GET", "/legacy/"+id, "", 200)
	var body struct {
		Data *legacySwarmHistory `json:"data"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	return body.Data
}

func TestProjectOKRLegacyHistoryUsesBoundReadOnlyArchiveAndWAL(t *testing.T) {
	a, id, path, _ := legacyHistoryFixture(t)
	beforeDB, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	beforeWAL, err := os.ReadFile(path + "-wal")
	if err != nil {
		t.Fatal(err)
	}
	history := requestLegacyHistory(t, a, id)
	if history == nil || !history.Historical || history.Verified || history.Source != "legacy" || len(history.Members) != 1 || len(history.Tasks) != 1 || len(history.Posts) != 2 {
		t.Fatalf("history: %+v", history)
	}
	if history.Tasks[0].Status != "done" || history.Posts[1].ReplyTo == nil || *history.Posts[1].ReplyTo != 1 {
		t.Fatal(history)
	}
	if len(history.UnavailableSources) != 0 {
		t.Fatal(history.UnavailableSources)
	}
	afterDB, _ := os.ReadFile(path)
	afterWAL, _ := os.ReadFile(path + "-wal")
	if string(beforeDB) != string(afterDB) || string(beforeWAL) != string(afterWAL) {
		t.Fatal("history read mutated source database")
	}
	dir, _ := a.Projects.Dir(id)
	if _, err := os.Stat(filepath.Join(dir, ".roami")); !os.IsNotExist(err) {
		t.Fatal("history GET migrated project files", err)
	}

}

func TestProjectOKRLegacyHistoryRefusesCrossProjectAndSymlinkSources(t *testing.T) {
	a, id, path, _ := legacyHistoryFixture(t)
	if _, err := a.Meta.Exec(`UPDATE swarms SET dir=? WHERE id='legacy-1'`, t.TempDir()); err != nil {
		t.Fatal(err)
	}
	if history := requestLegacyHistory(t, a, id); history != nil {
		t.Fatal("cross-project legacy group exposed", history)
	}
	dir, _ := a.Projects.Dir(id)
	if _, err := a.Meta.Exec(`UPDATE swarms SET dir=? WHERE id='legacy-1'`, dir); err != nil {
		t.Fatal(err)
	}
	outside := filepath.Join(t.TempDir(), "foreign.db")
	if err := os.WriteFile(outside, []byte("private"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, path); err != nil {
		t.Fatal(err)
	}
	history := requestLegacyHistory(t, a, id)
	if history == nil || len(history.Members) != 1 || len(history.Posts) != 0 || !strings.Contains(strings.Join(history.UnavailableSources, ","), "posts") {
		t.Fatal(history)
	}
	if _, _, err := openLegacyGroup(a.Meta.Info().Path, "../escape"); err == nil {
		t.Fatal("unsafe source identifier accepted")
	}
	for _, table := range []string{"swarm_members", "swarm_cards"} {
		if _, err := a.Meta.Exec("DELETE FROM " + table + " WHERE swarm_id='legacy-1'"); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := a.Meta.Exec(`UPDATE swarms SET id='../escape' WHERE id='legacy-1'`); err != nil {
		t.Fatal(err)
	}
	if history := requestLegacyHistory(t, a, id); history != nil {
		t.Fatal("unsafe bound source identifier exposed")
	}

}

func TestProjectOKRLegacyHistoryFallbackColumnsAndLimits(t *testing.T) {
	a, id, _, group := legacyHistoryFixture(t)
	if _, err := a.Meta.Exec(`DELETE FROM swarm_members WHERE swarm_id='legacy-1'`); err != nil {
		t.Fatal(err)
	}
	if _, err := a.Meta.Exec(`DELETE FROM swarm_cards WHERE swarm_id='legacy-1'`); err != nil {
		t.Fatal(err)
	}
	if _, err := group.Exec(`INSERT INTO members(name,task) VALUES('old-worker','old schema')`); err != nil {
		t.Fatal(err)
	}
	if _, err := group.Exec(`INSERT INTO cards(id,title,col) VALUES('old-task','old card','review')`); err != nil {
		t.Fatal(err)
	}
	for i := 3; i <= 205; i++ {
		if _, err := group.Exec(`INSERT INTO posts(id,text) VALUES(?,?)`, i, "entry"); err != nil {
			t.Fatal(err)
		}
	}
	history := requestLegacyHistory(t, a, id)
	if history == nil || len(history.Members) != 1 || history.Members[0].Name != "old-worker" || len(history.Tasks) != 1 || history.Tasks[0].Status != "review" || len(history.Posts) != 200 || !history.Truncated["posts"] || history.Posts[0].ID != 6 {
		t.Fatalf("history: %+v", history)
	}
}
