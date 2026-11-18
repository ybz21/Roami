package swarm

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"testing"
)

func TestExecutionMigrationUsesOwnerScopedAtomicRequestWithoutDispatch(t *testing.T) {
	calls := 0
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.Method != "POST" || r.URL.Path != "/v1/swarms/"+fixtureID+"/execution-migrations" {
			t.Fatalf("unexpected dispatch %s %s", r.Method, r.URL.Path)
		}
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body["expectedRevision"] != float64(4) || body["commandKey"] != "switch-1" {
			t.Fatalf("lost identity: %#v", body)
		}
		m := body["members"].([]any)[0].(map[string]any)
		if m["memberId"] != "original-member" || m["executor"] != "claude" || m["model"] != "free" || m["preparedLaunchKey"] != "prepared-role" {
			t.Fatalf("lost configuration: %#v", m)
		}
		apiReply(w, map[string]any{"id": fixtureID, "revision": 5, "paused": true})
	})
	var output bytes.Buffer
	err := runCommand(context.Background(), rt, []string{"migrate", fixtureID, "--file", "-", "--json"}, &output, strings.NewReader(`{"commandKey":"switch-1","expectedRevision":4,"members":[{"memberId":"original-member","executor":"claude","model":"free","preparedLaunchKey":"prepared-role"}]}`))
	if err != nil || calls != 1 || !strings.Contains(output.String(), `"paused":true`) {
		t.Fatalf("migration err=%v calls=%d output=%s", err, calls, output.String())
	}
}

func TestMembersJSONRetainsPerMemberModel(t *testing.T) {
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		apiReply(w, map[string]any{"id": fixtureID, "memberProtocol": 1, "members": []any{map[string]any{"id": "original-member", "executor": "claude", "model": "free", "provider": map[string]any{"generation": 2, "sessionId": "prepared-session", "executor": "claude", "model": "free", "launchKey": "prepared-role"}}}})
	})
	out := commandResult(t, rt, "members", fixtureID, "--json")
	if !strings.Contains(out, `"model":"free"`) || !strings.Contains(out, `"sessionId":"prepared-session"`) || !strings.Contains(out, `"generation":2`) {
		t.Fatalf("model missing %s", out)
	}
}
