package okr

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"github.com/ybz21/Roami/internal/agent"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestProjectFileDefinitionsDriveCollectionAndSurviveDatabaseReplacement(t *testing.T) {
	s, project := fileStore(t)
	w, err := s.Save("project", githubConfig())
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(project, ".roami", "okr")
	editJSON(t, filepath.Join(root, "agents/team.json"), func(v map[string]any) {
		v["roles"] = []TeamRole{{ID: "editor", Name: "Editor", Executor: "codex", Duty: "Prepare drafts with evidence"}, {ID: "analyst", Name: "Analyst", Executor: "native", Duty: "Verify dated source observations"}}
	})
	editJSON(t, filepath.Join(root, "dashboard.json"), func(v map[string]any) {
		v["widgets"] = []any{map[string]any{"id": "stars", "type": "metricTrend", "title": "Repository stars", "metricIds": []string{"users"}}}
	})
	editJSON(t, filepath.Join(root, "okr.json"), func(v map[string]any) {
		v["metrics"].([]any)[0].(map[string]any)["repo"] = "owner/confirmed"
	})
	editJSON(t, filepath.Join(root, "connectors/users/connector.json"), func(v map[string]any) {
		v["repo"] = "owner/confirmed"
	})
	pending, err := s.Get("project")
	if err != nil {
		t.Fatal(err)
	}
	if !pending.ProjectFiles.PendingChanges || pending.Metrics[0].Repo != "owner/project" || len(pending.Dashboard.Widgets) != 3 {
		t.Fatal("draft definitions replaced the confirmed dashboard", pending)
	}
	w, err = s.Sync("project", w.Revision)
	if err != nil {
		t.Fatal(err)
	}
	if w.ProjectFiles.PendingChanges || len(w.Dashboard.Widgets) != 1 || w.Dashboard.Widgets[0].Title != "Repository stars" {
		t.Fatal("confirmed dashboard did not use project definitions", w)
	}
	if len(w.Team.Roles) != 2 || w.Team.Roles[0].ID != "editor" || w.Swarm != "" {
		t.Fatal("team definitions missing or treated as a running Swarm", w)
	}
	calls, unavailable := 0, false
	g := GitHub{Client: &http.Client{Transport: roundTrip(func(req *http.Request) (*http.Response, error) {
		calls++
		if req.URL.Path != "/repos/owner/confirmed" {
			t.Fatalf("collector ignored confirmed connector source: %s", req.URL)
		}
		if unavailable {
			return githubResponse(http.StatusServiceUnavailable, `{}`), nil
		}
		return githubResponse(http.StatusOK, `{"id":42,"full_name":"owner/confirmed","private":false,"stargazers_count":24,"forks_count":3}`), nil
	})}}
	w, err = s.Collect(context.Background(), g, "project", w.Revision, false)
	if err != nil {
		t.Fatal(err)
	}
	if calls != 1 || len(w.Observations) != 1 || w.Observations[0].Value != 24 || w.Metrics[0].SourceKey != "github:42:stars" {
		t.Fatal("connector result missing from confirmed workspace", w)
	}
	f, err := os.Open(filepath.Join(root, "data/observations.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	var observations []Observation
	for scanner.Scan() {
		var observation Observation
		if err := json.Unmarshal(scanner.Bytes(), &observation); err != nil {
			t.Fatal(err)
		}
		observations = append(observations, observation)
	}
	if scanner.Err() != nil || !reflect.DeepEqual(observations, w.Observations) {
		t.Fatal("JSONL export differs from confirmed facts", observations, scanner.Err())
	}
	pointerFile := filepath.Join(root, "state/current.json")
	pointerBefore, err := os.ReadFile(pointerFile)
	if err != nil {
		t.Fatal(err)
	}
	unavailable = true
	if _, err := s.Collect(context.Background(), g, "project", w.Revision, false); !errors.Is(err, ErrSource) {
		t.Fatal("unavailable connector was accepted", err)
	}
	pointerAfter, err := os.ReadFile(pointerFile)
	if err != nil || string(pointerBefore) != string(pointerAfter) {
		t.Fatal("failed connector changed confirmed revision", err)
	}
	// A fresh catalog must recover facts from the project, not a workspace row in SQLite.
	reopened, _ := testStore(t)
	reopened.SetProjects(s.projects)
	got, err := reopened.Get("project")
	if err != nil || !reflect.DeepEqual(w, got) {
		t.Fatal("file-backed dashboard did not survive an empty catalog", got, err)
	}
	legacy, err := read(reopened.db, "project")
	if err != nil || legacy != nil {
		t.Fatal("file-backed facts were copied into legacy workspace storage", legacy, err)
	}
	t.Log("PASS: edit definitions -> confirm revision -> connector fetch -> JSONL + snapshot -> recover with fresh SQLite catalog; failed fetch preserves revision")
}

func TestProjectTeamDefinitionValidationAndLegacySaves(t *testing.T) {
	s, project := fileStore(t)
	c := testConfig()
	c.Team = &TeamDefinition{SchemaVersion: 1, Roles: []TeamRole{{ID: "editor", Name: "Editor", Executor: "codex", Duty: "Draft"}}}
	w, err := s.Save("project", c)
	if err != nil {
		t.Fatal(err)
	}
	legacy := w.Config
	legacy.Team = nil
	w, err = s.Save("project", legacy)
	if err != nil || w.Team == nil || !reflect.DeepEqual(w.Team, c.Team) {
		t.Fatal("a client without the team field erased persistent roles", w, err)
	}
	for _, team := range []TeamDefinition{
		{SchemaVersion: 2, Roles: []TeamRole{}},
		{SchemaVersion: 1},
		{SchemaVersion: 1, Roles: []TeamRole{{ID: "../escape", Name: "Editor", Executor: "codex", Duty: "Draft"}}},
		{SchemaVersion: 1, Roles: []TeamRole{{ID: "editor", Name: "Editor", Executor: "shell", Duty: "Draft"}}},
		{SchemaVersion: 1, Roles: []TeamRole{{ID: "editor", Name: "Editor", Executor: "codex", Duty: ""}}},
		{SchemaVersion: 1, Roles: []TeamRole{{ID: "coordinator", Name: "MAIN", Executor: "native", Duty: "Coordinate"}}},
		{SchemaVersion: 1, Roles: []TeamRole{{ID: "coordinator", Name: "Leader", Executor: "native", Duty: "Coordinate"}}},
		{SchemaVersion: 1, Roles: []TeamRole{{ID: "editor", Name: strings.Repeat("编", 81), Executor: "codex", Duty: "Draft"}}},
		{SchemaVersion: 1, Roles: []TeamRole{c.Team.Roles[0], c.Team.Roles[0]}},
		{SchemaVersion: 1, Roles: []TeamRole{c.Team.Roles[0], {ID: "other", Name: "Editor", Executor: "native", Duty: "Verify"}}},
	} {
		c := w.Config
		c.Team = &team
		if _, err := s.Save("project", c); !errors.Is(err, ErrInvalid) {
			t.Fatal("invalid role definition accepted", team, err)
		}
	}
	teamFile := filepath.Join(project, bundleRoot, "agents/team.json")
	if err := os.Remove(teamFile); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Sync("project", w.Revision); !errors.Is(err, ErrInvalid) {
		t.Fatal("missing team file silently removed confirmed roles", err)
	}
	got, err := s.Get("project")
	if err != nil || got.Team == nil || !reflect.DeepEqual(got.Team, w.Team) || !got.ProjectFiles.PendingChanges {
		t.Fatal("missing draft team file replaced confirmed roles", got, err)
	}
}

func TestProjectTeamAcceptsRegistryUnicodeNameLimit(t *testing.T) {
	s, _ := fileStore(t)
	c := testConfig()
	c.Team = &TeamDefinition{SchemaVersion: 1, Roles: []TeamRole{{ID: "editor", Name: strings.Repeat("编", 80), Executor: "codex", Duty: "Draft"}}}
	w, err := s.Save("project", c)
	if err != nil || w.Team.Roles[0].Name != c.Team.Roles[0].Name {
		t.Fatal("valid managed-member name was rejected or changed", w, err)
	}
}

func TestProjectFilesWithoutTeamDefinitionRemainReadable(t *testing.T) {
	s, project := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(project, bundleRoot)
	var pointer confirmedPointer
	body, err := os.ReadFile(filepath.Join(root, "state/current.json"))
	if err != nil || json.Unmarshal(body, &pointer) != nil {
		t.Fatal(err)
	}
	editJSON(t, filepath.Join(root, pointer.Snapshot), func(v map[string]any) {
		delete(v["workspace"].(map[string]any), "team")
	})
	if err := os.Remove(filepath.Join(root, "agents/team.json")); err != nil {
		t.Fatal(err)
	}
	got, err := s.Get("project")
	if err != nil || got.Team != nil || got.ProjectFiles.PendingChanges {
		t.Fatal("pre-team project was treated as a broken bundle", got, err)
	}
	got, err = s.Sync("project", w.Revision)
	if err != nil || got.Team == nil || got.Team.Roles == nil || len(got.Team.Roles) != 0 || got.ProjectFiles.PendingChanges {
		t.Fatal("legacy sync did not create an empty desired-team file", got, err)
	}
}

func TestTeamAcceptsEveryRegisteredHarness(t *testing.T) {
	for _, kind := range agent.Kinds() {
		config := testConfig()
		config.Team = &TeamDefinition{SchemaVersion: 1, Roles: []TeamRole{{ID: "editor", Name: "Editor", Executor: kind, Duty: "Prepare evidence"}}}
		if err := validate(&config); err != nil {
			t.Fatalf("registered %s rejected: %v", kind, err)
		}
	}
}
