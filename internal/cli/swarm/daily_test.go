package swarm

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestDailyWakeCarriesOnlyExistingGoalIdentity(t *testing.T) {
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" || r.URL.Path != "/v1/swarms/"+fixtureID+"/goal/daily" {
			t.Fatalf("unexpected daily wake %s %s", r.Method, r.URL)
		}
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if len(body) != 7 || body["delegationId"] != "original-goal" || body["projectId"] != "project-a" || body["conversationId"] != "original-main" || body["timezone"] != "Asia/Shanghai" || body["date"] != "2026-11-08" || body["slot"] != "morning" || body["dryRun"] != true {
			t.Fatal(body)
		}
		apiReply(w, map[string]any{"state": "prepared", "delivered": false})
	})
	output := commandResult(t, rt, "daily", fixtureID, "--delegation", "original-goal", "--project", "project-a", "--main-conversation", "original-main", "--timezone", "Asia/Shanghai", "--date", "2026-11-08", "--slot", "morning", "--dry-run", "--json")
	if !strings.Contains(output, `"prepared"`) || strings.Contains(output, `"messageId"`) {
		t.Fatal(output)
	}
}

func TestDailyWakeRejectsAgentShellBeforeOpeningClient(t *testing.T) {
	for _, key := range []string{"ROAMI_AGENT_CALLER_ROLE", "ROAMI_AGENT_TURN_ID"} {
		t.Run(key, func(t *testing.T) {
			t.Setenv(key, "worker")
			err := Run(runtime.Runtime{}, []string{"daily", fixtureID}, io.Discard)
			if err == nil || !strings.Contains(err.Error(), "EXTERNAL_TRIGGER_REQUIRED") {
				t.Fatal(err)
			}
		})
	}
}

func TestDailyWakeDoesNotAcceptNewMessageOrIncompleteIdentity(t *testing.T) {
	for _, args := range [][]string{
		{"daily", fixtureID, "--prompt", "publish something new"},
		{"daily", fixtureID, "--project", "project-a"},
	} {
		if err := Run(runtime.Runtime{}, args, io.Discard); err == nil {
			t.Fatal("accepted incomplete identity or new user text", args)
		}
	}
}
