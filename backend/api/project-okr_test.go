package api

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/okr"
	"github.com/ybz21/Roami/backend/project"
	"github.com/ybz21/Roami/backend/ttmux"
	"github.com/ybz21/Roami/internal/metadb"
	storage "github.com/ybz21/Roami/internal/storage"
)

func projectOKRFixture(t *testing.T) (*API, *gin.Engine, string) {
	t.Helper()
	root := t.TempDir()
	paths := storage.Paths{Home: root, Data: root, Database: filepath.Join(root, "database"), Backup: filepath.Join(root, "backups")}
	store, err := okr.Open(paths)
	if err != nil {
		t.Fatal(err)
	}
	meta, err := storage.Open(root, storage.Options{DataDir: root})
	if err != nil {
		t.Fatal(err)
	}
	projects := project.NewStore(root, metadb.NewLocal(meta))
	if err := os.Mkdir(filepath.Join(root, "repo"), 0700); err != nil {
		t.Fatal(err)
	}
	projectID, _ := projects.Add(filepath.Join(root, "repo"), "Test")
	store.SetProjects(func() map[string]string {
		result := map[string]string{}
		for id, entry := range projects.Entries() {
			result[id] = entry.Dir
		}
		return result
	})
	a := &API{Projects: projects, ProjectOKR: store, Meta: metadb.NewLocal(meta)}
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/okr", a.ProjectOKROverview)
	r.GET("/projects/:key/okr", a.ProjectOKRGet)
	r.PUT("/projects/:key/okr", a.ProjectOKRSave)
	r.POST("/projects/:key/okr/sync", a.ProjectOKRSync)
	r.PUT("/projects/:key/okr/memory", a.ProjectOKRMemory)
	r.POST("/projects/:key/okr/observations", a.ProjectOKRObserve)
	r.POST("/projects/:key/okr/collect", a.ProjectOKRCollect)
	r.POST("/projects/:key/okr/reviews", a.ProjectOKRReview)
	r.GET("/projects/:key/okr/reviews/:reviewID/evidence", a.ProjectOKREvidence)
	return a, r, projectID
}

func TestProjectOKROverviewOnlyListsSavedObjectives(t *testing.T) {
	a, router, id := projectOKRFixture(t)
	other, _ := a.Projects.Add(t.TempDir(), "No objective")
	response := projectOKRRequest(t, router, "GET", "/okr", "", 200)
	if response.Body.String() != `{"data":[]}` {
		t.Fatal(response.Body.String())
	}
	projectOKRRequest(t, router, "PUT", "/projects/"+id+"/okr", projectOKRConfigJSON(), 200)
	response = projectOKRRequest(t, router, "GET", "/okr", "", 200)
	var body struct {
		Data []okr.Overview `json:"data"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil || len(body.Data) != 1 || body.Data[0].ProjectID != id {
		t.Fatal(response.Body.String(), err)
	}
	if w, err := a.ProjectOKR.Get(other); err != nil || w != nil {
		t.Fatal("overview created a workspace", w, err)
	}
	a.Projects.Remove(id)
	response = projectOKRRequest(t, router, "GET", "/okr", "", 200)
	if response.Body.String() != `{"data":[]}` {
		t.Fatal(response.Body.String())
	}
}

func projectOKRRequest(t *testing.T, router *gin.Engine, method, path, body string, status int) *httptest.ResponseRecorder {
	t.Helper()
	w := httptest.NewRecorder()
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	r.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, r)
	if w.Code != status {
		t.Fatalf("%s %s: status=%d want=%d body=%s", method, path, w.Code, status, w.Body.String())
	}
	return w
}

func projectOKRConfigJSON() string {
	return `{"revision":0,"objective":"Grow adoption","startDate":"2000-01-01","endDate":"2999-12-31","keyResults":[{"id":"reach","title":"Reach users","horizon":"long","metricId":"users","target":100,"mode":"atLeast","dueDate":"2999-12-31"}],"metrics":[{"id":"users","name":"Users","unit":"people","source":"manual"}],"swarm":"","autoCollect":false}`
}

func decodeProjectOKR(t *testing.T, response *httptest.ResponseRecorder) *okr.Workspace {
	t.Helper()
	var body struct {
		Data *okr.Workspace `json:"data"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	return body.Data
}

func TestProjectOKRAPISavesDesiredTeamWithoutLaunchingSwarm(t *testing.T) {
	a, router, projectID := projectOKRFixture(t)
	var config okr.Config
	if err := json.Unmarshal([]byte(projectOKRConfigJSON()), &config); err != nil {
		t.Fatal(err)
	}
	config.Team = &okr.TeamDefinition{SchemaVersion: 1, Roles: []okr.TeamRole{{ID: "editor", Name: "Editor", Executor: "codex", Duty: "Prepare verified drafts"}}}
	body, err := json.Marshal(config)
	if err != nil {
		t.Fatal(err)
	}
	path := "/projects/" + projectID + "/okr"
	w := decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", path, string(body), 200))
	if w.Team == nil || len(w.Team.Roles) != 1 || w.Team.Roles[0].ID != "editor" || w.Swarm != "" || w.ProjectFiles == nil || !w.ProjectFiles.TeamRoleBindings {
		t.Fatal("desired team was not preserved independently of a live Swarm", w)
	}
	entry, _ := a.Projects.Entry(projectID)
	file, err := os.ReadFile(filepath.Join(entry.Dir, ".roami/okr/agents/team.json"))
	var team okr.TeamDefinition
	if err != nil || json.Unmarshal(file, &team) != nil || len(team.Roles) != 1 || team.Roles[0].Duty != config.Team.Roles[0].Duty {
		t.Fatal("team definition was not published in the project directory", string(file), err)
	}
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "GET", path, "", 200))
	if w.Team == nil || w.Team.Roles[0].Executor != "codex" {
		t.Fatal("project API did not load the confirmed file definition", w)
	}
}

func TestProjectOKRAPIHistoryRevisionsAndProjectAliases(t *testing.T) {
	a, router, projectID := projectOKRFixture(t)
	path := "/projects/" + projectID + "/okr"
	if w := decodeProjectOKR(t, projectOKRRequest(t, router, "GET", path, "", 200)); w != nil {
		t.Fatal(w)
	}
	w := decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", path, projectOKRConfigJSON(), 200))
	if w.Revision != 1 || w.ProjectID != projectID || w.Metrics[0].SourceKey != "manual:users" {
		t.Fatal(w)
	}
	projectOKRRequest(t, router, "PUT", path, projectOKRConfigJSON(), 409)
	projectOKRRequest(t, router, "POST", path+"/observations", `{"revision":1,"metricId":"users","date":"2001-01-01","value":0,"note":"first"}`, 200)
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "POST", path+"/observations", `{"revision":2,"metricId":"users","date":"2001-01-01","value":-2,"note":"corrected"}`, 200))
	if len(w.Observations) != 2 || w.Observations[0].Value != 0 || w.Observations[1].Value != -2 {
		t.Fatal(w)
	}
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "POST", path+"/reviews", `{"revision":3,"summary":"Reviewed evidence","actions":"Follow up"}`, 200))
	if w.Revision != 4 || len(w.Reviews) != 1 || w.Reviews[0].EvidenceRevision != 3 {
		t.Fatal(w)
	}
	snapshot := decodeProjectOKR(t, projectOKRRequest(t, router, "GET", path+"/reviews/"+w.Reviews[0].ID+"/evidence", "", 200))
	if snapshot.Revision != 3 || len(snapshot.Observations) != 2 || len(snapshot.Reviews) != 0 {
		t.Fatal(snapshot)
	}
	otherID, _ := a.Projects.Add(t.TempDir(), "Other")
	projectOKRRequest(t, router, "GET", "/projects/"+otherID+"/okr/reviews/"+w.Reviews[0].ID+"/evidence", "", 404)
	projectOKRRequest(t, router, "POST", path+"/collect", `{"revision":3}`, 409)
	projectOKRRequest(t, router, "POST", path+"/collect", `{"revision":4}`, 400)
	// Merge an older project identity into this entry, then open its old URL.
	alias, _ := a.Projects.Add(t.TempDir(), "Old")
	dir, _ := a.Projects.Dir(projectID)
	if got := a.Projects.SetDir(alias, dir); got != projectID {
		t.Fatal(got)
	}
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "GET", "/projects/"+alias+"/okr", "", 200))
	if w.ProjectID != projectID || w.Revision != 4 {
		t.Fatal(w)
	}
	projectOKRRequest(t, router, "GET", "/projects/missing/okr", "", 404)
}

func TestProjectOKRAPIRejectsHistoryNullValuesAndMalformedInput(t *testing.T) {
	_, router, projectID := projectOKRFixture(t)
	path := "/projects/" + projectID + "/okr"
	for _, body := range []string{
		strings.Replace(projectOKRConfigJSON(), `"revision":0,`, "", 1),
		strings.Replace(projectOKRConfigJSON(), `"revision":0`, `"revision":null`, 1),
		strings.Replace(projectOKRConfigJSON(), `"target":100,`, "", 1),
		strings.Replace(projectOKRConfigJSON(), `"target":100`, `"target":null`, 1),
		strings.Replace(projectOKRConfigJSON(), `"target":100`, `"target":1e309`, 1),
		strings.Replace(projectOKRConfigJSON(), `"autoCollect":false`, `"autoCollect":false,"observations":[]`, 1),
		projectOKRConfigJSON() + `{}`,
	} {
		projectOKRRequest(t, router, "PUT", path, body, 400)
	}
	if w := decodeProjectOKR(t, projectOKRRequest(t, router, "GET", path, "", 200)); w != nil {
		t.Fatal("invalid requests created workspace")
	}
	projectOKRRequest(t, router, "PUT", path, projectOKRConfigJSON(), 200)
	for _, body := range []string{
		`{"revision":1,"metricId":"users","date":"2001-01-01"}`,
		`{"revision":1,"metricId":"users","date":"2001-01-01","value":null}`,
		`{"revision":1,"metricId":"users","date":"2001-02-30","value":0}`,
		`{"revision":1,"metricId":"missing","date":"2001-01-01","value":0}`,
		`{"revision":1,"metricId":"users","date":"2001-01-01","value":"0"}`,
	} {
		projectOKRRequest(t, router, "POST", path+"/observations", body, 400)
	}
	projectOKRRequest(t, router, "POST", path+"/reviews", `{"revision":1,"summary":" "}`, 400)
	w := decodeProjectOKR(t, projectOKRRequest(t, router, "GET", path, "", 200))
	if w.Revision != 1 || len(w.Observations) != 0 || len(w.Reviews) != 0 {
		t.Fatal(w)
	}
}

func TestProjectOKRAPIBindsManagedSwarmByStableID(t *testing.T) {
	const id = "sw-0123456789abcdef0123456789abcdef"
	const other = "sw-1123456789abcdef0123456789abcdef"
	for _, tc := range []struct {
		name, key, directory string
		status               int
	}{
		{"id", id, `{"data":[{"id":"` + id + `","name":"existing-group"}]}`, 200},
		{"unique name", "existing-group", `{"data":[{"id":"` + id + `","name":"existing-group"}]}`, 200},
		{"duplicate name", "existing-group", `{"data":[{"id":"` + id + `","name":"existing-group"},{"id":"` + other + `","name":"existing-group"}]}`, 400},
		{"archived", id, `{"data":[{"id":"` + id + `","name":"existing-group","archived":true}]}`, 400},
		{"legacy only", "legacy-group", `{"data":[]}`, 400},
	} {
		t.Run(tc.name, func(t *testing.T) {
			a, router, projectID := projectOKRFixture(t)
			if _, err := a.Meta.Exec(`INSERT INTO swarms(id,name,goal,status,created,dir,supervisor) VALUES('legacy','legacy-group','test','running','','','')`); err != nil {
				t.Fatal(err)
			}
			bin := filepath.Join(t.TempDir(), "directory-cli")
			script := "#!/bin/sh\n[ \"$*\" = 'swarm ls --json' ] || exit 1\ncat <<'JSON'\n" + tc.directory + "\nJSON\n"
			if err := os.WriteFile(bin, []byte(script), 0700); err != nil {
				t.Fatal(err)
			}
			a.TT = ttmux.New(bin)
			body := strings.Replace(projectOKRConfigJSON(), `"swarm":""`, `"swarm":"`+tc.key+`"`, 1)
			response := projectOKRRequest(t, router, "PUT", "/projects/"+projectID+"/okr", body, tc.status)
			if tc.status == 200 && decodeProjectOKR(t, response).Swarm != id {
				t.Fatal(response.Body.String())
			}
		})
	}
}

type okrAPITransport func(*http.Request) (*http.Response, error)

func (f okrAPITransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestProjectOKRAPICollectionFailurePreservesLastKnownValue(t *testing.T) {
	a, router, projectID := projectOKRFixture(t)
	path := "/projects/" + projectID + "/okr"
	config := strings.Replace(projectOKRConfigJSON(), `"source":"manual"`, `"source":"github","repo":"owner/repo","field":"stars"`, 1)
	projectOKRRequest(t, router, "PUT", path, config, 200)
	status, value := 200, `{"id":42,"full_name":"owner/repo","private":false,"stargazers_count":7,"forks_count":1}`
	a.projectOKRGitHub.Client = &http.Client{Transport: okrAPITransport(func(r *http.Request) (*http.Response, error) {
		if r.URL.String() != "https://api.github.com/repos/owner/repo" {
			t.Fatal(r.URL)
		}
		return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader(value)), Header: http.Header{}}, nil
	})}
	w := decodeProjectOKR(t, projectOKRRequest(t, router, "POST", path+"/collect", `{"revision":1}`, 200))
	if w.Revision != 2 || len(w.Observations) != 1 || w.Observations[0].Value != 7 || w.Metrics[0].SourceKey != "github:42:stars" {
		t.Fatal(w)
	}
	status = 403
	failure := projectOKRRequest(t, router, "POST", path+"/collect", `{"revision":2}`, 502)
	if !strings.Contains(failure.Body.String(), `"error":"OKR_SOURCE_FAILED"`) {
		t.Fatal(failure.Body.String())
	}
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "GET", path, "", 200))
	if w.Revision != 2 || len(w.Observations) != 1 || w.Observations[0].Value != 7 {
		t.Fatal("collection failure lost evidence")
	}
	projectOKRRequest(t, router, "POST", path+"/observations", `{"revision":2,"metricId":"users","date":"2001-01-01","value":123}`, 400)
}

func TestProjectOKRSyncAndSharedMemory(t *testing.T) {
	a, router, id := projectOKRFixture(t)
	endpoint := "/projects/" + id + "/okr"
	w := decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", endpoint, projectOKRConfigJSON(), 200))
	if w.ProjectFiles == nil {
		t.Fatal("project file metadata absent")
	}
	payload, _ := json.Marshal(map[string]string{"content": "Team context", "expectedSha256": w.ProjectFiles.TeamMemorySha256})
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", endpoint+"/memory", string(payload), 200))
	if w.ProjectFiles.TeamMemory != "Team context" || w.Revision != 1 {
		t.Fatal(w)
	}
	projectOKRRequest(t, router, "PUT", endpoint+"/memory", string(payload), 409)
	projectOKRRequest(t, router, "PUT", endpoint+"/memory", `{"content":"missing hash"}`, 400)
	dir, _ := a.Projects.Dir(id)
	file := filepath.Join(dir, ".roami", "okr", "okr.json")
	b, err := os.ReadFile(file)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(file, []byte(strings.Replace(string(b), "Grow adoption", "Edited locally", 1)), 0600); err != nil {
		t.Fatal(err)
	}
	pending := decodeProjectOKR(t, projectOKRRequest(t, router, "GET", endpoint, "", 200))
	if !pending.ProjectFiles.PendingChanges || pending.Objective != "Grow adoption" {
		t.Fatal(pending)
	}
	pendingSave := strings.Replace(projectOKRConfigJSON(), `"revision":0`, `"revision":1`, 1)
	response := projectOKRRequest(t, router, "PUT", endpoint, pendingSave, 409)
	if !strings.Contains(response.Body.String(), "OKR_FILES_PENDING") {
		t.Fatal(response.Body.String())
	}

	w = decodeProjectOKR(t, projectOKRRequest(t, router, "POST", endpoint+"/sync", `{"revision":1}`, 200))
	if w.Objective != "Edited locally" || w.Revision != 2 || w.ProjectFiles.PendingChanges {
		t.Fatal(w)
	}
	projectOKRRequest(t, router, "POST", endpoint+"/sync", `{"revision":1}`, 409)
}

func TestProjectOKRMemoryAppendPreservesPriorAndRejectsUnknownMode(t *testing.T) {
	_, router, id := projectOKRFixture(t)
	endpoint := "/projects/" + id + "/okr"
	w := decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", endpoint, projectOKRConfigJSON(), 200))
	memory := func(mode, content, hash string, status int) *httptest.ResponseRecorder {
		payload, _ := json.Marshal(map[string]string{"mode": mode, "content": content, "expectedSha256": hash})
		return projectOKRRequest(t, router, "PUT", endpoint+"/memory", string(payload), status)
	}
	w = decodeProjectOKR(t, memory("append", "Existing receipt", w.ProjectFiles.TeamMemorySha256, 200))
	previous := w.ProjectFiles.TeamMemorySha256
	w = decodeProjectOKR(t, memory("append", "New dated fact", previous, 200))
	if w.ProjectFiles.TeamMemory != "Existing receipt\n\nNew dated fact" {
		t.Fatal(w.ProjectFiles.TeamMemory)
	}
	memory("append", "Stale", previous, 409)
	memory("probe", "Wrong", w.ProjectFiles.TeamMemorySha256, 400)
	current := decodeProjectOKR(t, projectOKRRequest(t, router, "GET", endpoint, "", 200))
	if current.ProjectFiles.TeamMemory != w.ProjectFiles.TeamMemory {
		t.Fatal("failed write changed memory")
	}
}
