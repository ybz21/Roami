package api

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/okr"
	"github.com/ybz21/Roami/backend/ttmux"
)

const bindingSwarm = "sw-0123456789abcdef0123456789abcdef"
const bindingMember = "0123456789abcdef0123456789abcdef"

func roleBindingFixture(t *testing.T) (*API, *gin.Engine, string, okr.Config, map[string]any, string) {
	t.Helper()
	a, router, projectID := projectOKRFixture(t)
	var config okr.Config
	if err := json.Unmarshal([]byte(projectOKRConfigJSON()), &config); err != nil {
		t.Fatal(err)
	}
	config.Swarm = bindingSwarm
	memberID := bindingMember
	config.Team = &okr.TeamDefinition{SchemaVersion: 1, Roles: []okr.TeamRole{{ID: "writer", Name: "Content", Executor: "codex", Duty: "Write verified content", MemberID: &memberID}}}
	snapshot := map[string]any{"id": bindingSwarm, "archived": false, "memberProtocol": 1, "target": map[string]any{"kind": "project", "projectId": projectID}, "members": []any{map[string]any{"id": bindingMember, "swarm_id": bindingSwarm, "executor": "codex"}}}
	bin := filepath.Join(t.TempDir(), "binding-cli")
	script := "#!/bin/sh\nset -eu\ncase \"$*\" in\n'swarm ls --json') cat \"$0.ls\";;\n'swarm status " + bindingSwarm + " --json') cat \"$0.status\";;\n*) exit 9;;\nesac\n"
	if err := os.WriteFile(bin, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(bin+".ls", []byte(`{"data":[{"id":"`+bindingSwarm+`","name":"Team"}]}`), 0600); err != nil {
		t.Fatal(err)
	}
	a.TT = ttmux.New(bin)
	return a, router, projectID, config, snapshot, bin + ".status"
}

func writeBindingSnapshot(t *testing.T, file string, snapshot map[string]any) {
	t.Helper()
	body, err := json.Marshal(map[string]any{"data": snapshot})
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(file, body, 0600); err != nil {
		t.Fatal(err)
	}
}
func bindingConfigBody(t *testing.T, config okr.Config) string {
	t.Helper()
	body, err := json.Marshal(config)
	if err != nil {
		t.Fatal(err)
	}
	return string(body)
}

func TestProjectOKRRoleBindingRoundTripAndOlderClient(t *testing.T) {
	a, router, id, config, snapshot, file := roleBindingFixture(t)
	writeBindingSnapshot(t, file, snapshot)
	endpoint := "/projects/" + id + "/okr"
	w := decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", endpoint, bindingConfigBody(t, config), 200))
	if w.Team.Roles[0].MemberID == nil || *w.Team.Roles[0].MemberID != bindingMember {
		t.Fatal(w.Team)
	}
	config = w.Config
	config.Team.Roles[0].MemberID = nil
	config.Objective = "Updated by older client"
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", endpoint, bindingConfigBody(t, config), 200))
	if *w.Team.Roles[0].MemberID != bindingMember {
		t.Fatal("older client lost binding", w.Team)
	}
	projectOKRRequest(t, router, "PUT", endpoint, bindingConfigBody(t, config), 409)
	entry, _ := a.Projects.Entry(id)
	raw, err := os.ReadFile(filepath.Join(entry.Dir, ".roami/okr/agents/team.json"))
	var team okr.TeamDefinition
	if err != nil || json.Unmarshal(raw, &team) != nil || *team.Roles[0].MemberID != bindingMember {
		t.Fatal(string(raw), err)
	}
	config = w.Config
	empty := ""
	config.Team.Roles[0].MemberID = &empty
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", endpoint, bindingConfigBody(t, config), 200))
	if *w.Team.Roles[0].MemberID != "" {
		t.Fatal("explicit clear ignored")
	}
}

func TestProjectOKRRoleBindingRejectsForeignAmbiguousAndInvalidMembers(t *testing.T) {
	for _, name := range []string{"foreign project", "session target", "foreign swarm", "foreign member", "archived", "legacy protocol", "missing member", "wrong executor", "duplicate member", "duplicate roles", "malformed member", "no team"} {
		t.Run(name, func(t *testing.T) {
			_, router, id, config, snapshot, file := roleBindingFixture(t)
			switch name {
			case "foreign project":
				snapshot["target"] = map[string]any{"kind": "project", "projectId": "other"}
			case "session target":
				snapshot["target"] = map[string]any{"kind": "session", "projectId": id}
			case "foreign swarm":
				snapshot["id"] = "sw-1123456789abcdef0123456789abcdef"
			case "foreign member":
				snapshot["members"].([]any)[0].(map[string]any)["swarm_id"] = "sw-1123456789abcdef0123456789abcdef"
			case "archived":
				snapshot["archived"] = true
			case "legacy protocol":
				snapshot["memberProtocol"] = 0
			case "missing member":
				snapshot["members"] = []any{}
			case "wrong executor":
				snapshot["members"].([]any)[0].(map[string]any)["executor"] = "native"
			case "duplicate member":
				snapshot["members"] = append(snapshot["members"].([]any), snapshot["members"].([]any)[0])
			case "duplicate roles":
				second := config.Team.Roles[0]
				second.ID = "editor"
				second.Name = "Editor"
				config.Team.Roles = append(config.Team.Roles, second)
			case "malformed member":
				bad := "role-label"
				config.Team.Roles[0].MemberID = &bad
			case "no team":
				config.Swarm = ""
			}
			writeBindingSnapshot(t, file, snapshot)
			endpoint := "/projects/" + id + "/okr"
			projectOKRRequest(t, router, "PUT", endpoint, bindingConfigBody(t, config), 400)
			if w := decodeProjectOKR(t, projectOKRRequest(t, router, "GET", endpoint, "", 200)); w != nil {
				t.Fatal("rejected binding changed confirmed files")
			}
		})
	}
}

func TestProjectOKRSyncValidatesPreservedBindingAndRollsBack(t *testing.T) {
	a, router, id, config, snapshot, file := roleBindingFixture(t)
	writeBindingSnapshot(t, file, snapshot)
	endpoint := "/projects/" + id + "/okr"
	w := decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", endpoint, bindingConfigBody(t, config), 200))
	entry, _ := a.Projects.Entry(id)
	path := filepath.Join(entry.Dir, ".roami/okr/agents/team.json")
	draft := *w.Team
	draft.Roles = append([]okr.TeamRole(nil), w.Team.Roles...)
	draft.Roles[0].MemberID = nil
	draft.Roles[0].Duty = "Updated duty"
	raw, _ := json.Marshal(draft)
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	snapshot["members"] = []any{}
	writeBindingSnapshot(t, file, snapshot)
	projectOKRRequest(t, router, "POST", endpoint+"/sync", `{"revision":1}`, 400)
	current := decodeProjectOKR(t, projectOKRRequest(t, router, "GET", endpoint, "", 200))
	if current.Revision != 1 || *current.Team.Roles[0].MemberID != bindingMember || !current.ProjectFiles.PendingChanges {
		t.Fatal("failed sync lost confirmed binding", current)
	}
	snapshot["members"] = []any{map[string]any{"id": bindingMember, "swarm_id": bindingSwarm, "executor": "codex"}}
	writeBindingSnapshot(t, file, snapshot)
	current = decodeProjectOKR(t, projectOKRRequest(t, router, "POST", endpoint+"/sync", `{"revision":1}`, 200))
	if current.Revision != 2 || *current.Team.Roles[0].MemberID != bindingMember || current.Team.Roles[0].Duty != "Updated duty" {
		t.Fatal(current)
	}
	config = current.Config
	config.Team.Roles[0].MemberID = nil
	config.Team.Roles[0].Executor = "native"
	projectOKRRequest(t, router, "PUT", endpoint, bindingConfigBody(t, config), 400)
}
