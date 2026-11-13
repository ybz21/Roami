package swarm

import (
	"encoding/json"
	"github.com/ybz21/Roami/internal/agent"
	"net/http"
	"strings"
	"testing"
)

const stableMemberFixtureID = "abcdef0123456789abcdef0123456789"

func TestMemberRegistrationDoesNotCreateAnExecutionPlan(t *testing.T) {
	calls := 0
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.Method != "POST" || r.URL.Path != "/v1/swarms/"+fixtureID+"/members" {
			t.Errorf("unexpected endpoint %s %s", r.Method, r.URL)
		}
		var request struct {
			Key      string     `json:"commandKey"`
			Revision int        `json:"expectedRevision"`
			Members  []member   `json:"members"`
			Items    []workItem `json:"items"`
		}
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Fatal(err)
		}
		if request.Key != "register-1" || request.Revision != 4 || len(request.Members) != 1 || request.Members[0].Name != "research" || request.Members[0].Executor != "native" || request.Members[0].Duty != "Read references" || len(request.Items) != 0 {
			t.Errorf("bad registration: %+v", request)
		}
		apiReply(w, map[string]any{"id": fixtureID, "revision": 5, "members": []member{{ID: stableMemberFixtureID, Name: "research", Executor: "native"}}})
	})
	output := commandResult(t, rt, "member", "register", fixtureID, "research", "--executor", "roami", "--duty", "Read references", "--key", "register-1", "--revision", "4", "--json")
	if calls != 1 || !strings.Contains(output, stableMemberFixtureID) {
		t.Fatalf("registration was not preserved: %d %s", calls, output)
	}
}

func TestMembersIncludesUnassignedRolesWithoutSyntheticTasks(t *testing.T) {
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		value := collaborationFixture()
		value.MemberProtocol = 1
		value.Members = []member{{ID: stableMemberFixtureID, Name: "research", Executor: "native", Duty: "Read references", State: "unassigned", MemoryPath: "members/" + stableMemberFixtureID + "/memory.md"}}
		value.Work = nil
		apiReply(w, value)
	})
	output := commandResult(t, rt, "members", fixtureID)
	if !strings.Contains(output, stableMemberFixtureID) || !strings.Contains(output, "待分配") || strings.Contains(output, "已完成") {
		t.Fatalf("unexpected role view: %s", output)
	}
	raw := commandResult(t, rt, "member", "ls", fixtureID, "--json")
	if !strings.Contains(raw, stableMemberFixtureID) || !strings.Contains(raw, `"taskId":""`) {
		t.Fatalf("missing role without task: %s", raw)
	}
}

func TestMemberInspectUsesStableIdentityAndRoundCursor(t *testing.T) {
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" || r.URL.Path != "/v1/swarms/"+fixtureID+"/members/"+stableMemberFixtureID || r.URL.Query().Get("before") != "30" || r.URL.Query().Get("limit") != "2" {
			t.Errorf("unexpected member read: %s %s", r.Method, r.URL)
		}
		apiReply(w, map[string]any{"member": member{ID: stableMemberFixtureID, Name: "research", Duty: "Read references", State: "waiting_user"}, "rounds": map[string]any{"items": []map[string]any{{"task_id": "original-task", "revision": 3, "state": "waiting_user", "request_text": "Check the latest reference"}}, "nextBefore": 12}})
	})
	output := commandResult(t, rt, "member", "inspect", fixtureID, stableMemberFixtureID, "--before", "30", "--limit", "2")
	for _, text := range []string{stableMemberFixtureID, "original-task @3", "需要输入", "--before 12"} {
		if !strings.Contains(output, text) {
			t.Fatalf("missing %q: %s", text, output)
		}
	}
}

func TestMemberInspectRejectsPathSelectorsAndInvalidCursorsBeforeRequest(t *testing.T) {
	calls := 0
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) { calls++; apiReply(w, map[string]any{}) })
	for _, args := range [][]string{{"member", "inspect", fixtureID, "../other"}, {"member", "inspect", fixtureID, stableMemberFixtureID, "--before", "0"}, {"member", "inspect", fixtureID, stableMemberFixtureID, "--limit", "51"}} {
		var out strings.Builder
		if err := runCommand(t.Context(), rt, args, &out, strings.NewReader("")); err == nil {
			t.Errorf("invalid request admitted: %v", args)
		}
	}
	if calls != 0 {
		t.Fatalf("invalid selectors sent %d requests", calls)
	}
}

func TestMembersPreservesLegacyJSONOnModernRuntime(t *testing.T) {
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		value := collaborationFixture()
		value.MemberProtocol = 0
		value.Members = []member{{ID: stableMemberFixtureID, Name: "api", State: "succeeded", TaskID: "task-api"}}
		apiReply(w, value)
	})
	output := commandResult(t, rt, "members", fixtureID, "--json")
	var result struct {
		Data []map[string]any `json:"data"`
	}
	if err := json.Unmarshal([]byte(output), &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Data) != 3 || result.Data[0]["id"] != "work-api" || result.Data[0]["member_name"] != "api" || result.Data[0]["task_id"] != "task-api" {
		t.Fatalf("legacy contract changed: %s", output)
	}
}

func TestMembersRetainsIdleNativeConversationFromAPI(t *testing.T) {
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		role := map[string]any{"id": stableMemberFixtureID, "name": "research", "executor": "native", "state": "unassigned", "roundCount": 0, "instance": map[string]any{"id": "native-instance", "conversationId": "reserved-conversation", "branchId": "reserved-branch", "state": "idle", "taskId": nil}}
		if strings.Contains(r.URL.Path, "/members/") {
			apiReply(w, map[string]any{"member": role, "rounds": map[string]any{"items": []any{}}})
			return
		}
		apiReply(w, map[string]any{"id": fixtureID, "memberProtocol": 1, "members": []any{role}, "work": []any{}})
	})
	output := commandResult(t, rt, "members", fixtureID, "--json")
	var result struct {
		Data []struct {
			TaskID     string          `json:"taskId"`
			RoundCount int             `json:"roundCount"`
			Instance   *memberInstance `json:"instance"`
		} `json:"data"`
	}
	if err := json.Unmarshal([]byte(output), &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Data) != 1 || result.Data[0].TaskID != "" || result.Data[0].RoundCount != 0 || result.Data[0].Instance == nil || result.Data[0].Instance.ConversationID != "reserved-conversation" {
		t.Fatalf("lost idle native instance: %s", output)
	}
	detail := commandResult(t, rt, "member", "inspect", fixtureID, stableMemberFixtureID)
	if !strings.Contains(detail, "对话: reserved-conversation") || strings.Contains(detail, "已完成") {
		t.Fatalf("misleading idle preview: %s", detail)
	}
}

func TestMemberRegistrationUsesAgentRegistry(t *testing.T) {
	for _, kind := range agent.Kinds() {
		t.Run(kind, func(t *testing.T) {
			rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
				var request struct {
					Members []member `json:"members"`
				}
				if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
					t.Fatal(err)
				}
				if len(request.Members) != 1 || request.Members[0].Executor != kind {
					t.Fatalf("wrong executor: %+v", request)
				}
				apiReply(w, map[string]any{"id": fixtureID, "revision": 5})
			})
			commandResult(t, rt, "member", "register", fixtureID, "research", "--executor", kind, "--duty", "Read references", "--key", "register-1", "--revision", "4", "--json")
		})
	}
}
