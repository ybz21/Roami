package swarm

import (
	"encoding/json"
	"net/http"
	"testing"
)

func TestInboxPreviewDoesNotPretendMainRead(t *testing.T) {
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" || r.URL.Path != "/v1/swarms/"+fixtureID+"/inbox" || r.URL.Query().Get("limit") != "5" {
			t.Fatalf("unexpected inbox preview %s %s", r.Method, r.URL)
		}
		apiReply(w, map[string]any{"swarmId": fixtureID, "items": []any{map[string]any{"postId": 7, "author": "data", "text": "Question", "readMs": nil, "sourceCurrent": true}}})
	})
	output := commandResult(t, rt, "inbox", fixtureID, "--limit", "5", "--json")
	var payload struct {
		Data struct {
			Items []map[string]any `json:"items"`
		} `json:"data"`
	}
	if err := json.Unmarshal([]byte(output), &payload); err != nil {
		t.Fatal(err)
	}
	if len(payload.Data.Items) != 1 || payload.Data.Items[0]["text"] != "Question" || payload.Data.Items[0]["readMs"] != nil {
		t.Fatal(output)
	}
}

func TestBoundInboxCarriesCurrentTaskIdentityToPrivateRoute(t *testing.T) {
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" || r.URL.Path != "/v1/swarms/"+fixtureID+"/member-inbox" {
			t.Fatalf("unexpected member inbox %s %s", r.Method, r.URL)
		}
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body["taskId"] != "task-api" || body["runId"] != "run-api" || body["taskRevision"] != float64(2) || body["before"] != float64(9) {
			t.Fatal(body)
		}
		apiReply(w, map[string]any{"swarmId": fixtureID, "memberId": "api", "items": []any{}})
	})
	commandResult(t, rt, "inbox", fixtureID, "--task", "task-api", "--run", "run-api", "--task-revision", "2", "--before", "9", "--json")
}

func TestMemberPostPreservesBusinessMessageAndThread(t *testing.T) {
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/swarms/"+fixtureID+"/member-posts" {
			t.Fatal(r.URL)
		}
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body["kind"] != "reply" || body["messageKey"] != "daily-answer" || body["replyTo"] != float64(7) || body["recipientMemberId"] != "receiver" {
			t.Fatal(body)
		}
		apiReply(w, map[string]any{"id": 8})
	})
	commandResult(t, rt, "post", fixtureID, "Here is the answer", "--key", "transport", "--task", "task-api", "--run", "run-api", "--task-revision", "2", "--kind", "reply", "--message-key", "daily-answer", "--reply-to", "7", "--recipient-member", "receiver", "--json")
}
