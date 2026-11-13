package swarm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/agentruntime"
	metadb "github.com/ybz21/Roami/internal/storage"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

const fixtureID = "sw-0123456789abcdef0123456789abcdef"

func collaborationFixture() snapshot {
	return snapshot{ID: fixtureID, Name: "协作验收", Goal: "交付可验证的结果", MainConversationID: "main-existing", MainState: "completed", Revision: 4, Sequence: 10, State: "review", Work: []workItem{
		{ID: "work-api", Member: "api", Executor: "codex", Title: "接口", State: "succeeded", TaskID: "task-api", Revision: 2, Goal: "接口目标", Acceptance: "接口测试通过", Attempt: &attempt{RunID: "run-api", State: "succeeded", Summary: "VERIFIED_RESULT", FinishedMS: 20}},
		{ID: "work-ui", Member: "ui", Executor: "claude", Title: "页面", State: "verifying", TaskID: "task-ui", Revision: 1, Attempt: &attempt{RunID: "run-ui", State: "reported", Summary: "UNVERIFIED_REPORT", FinishedMS: 21}},
		{ID: "work-check", Member: "check", Executor: "native", Title: "集成", State: "queued", Integration: 1, Dependencies: []dependency{{UpstreamID: "work-api", Revision: 2}}},
	}, Posts: []post{{ID: 1, Author: "human", Text: "原始要求", CreatedMS: 1}}, MainMessages: []mainMessage{{ID: "reply", Text: "Main 回复", CreatedMS: 2}}}
}
func fixtureRuntime(t *testing.T, handler http.HandlerFunc) runtime.Runtime {
	t.Helper()
	root := t.TempDir()
	paths, err := metadb.ResolvePaths(root, root)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = paths.Ensure(); err != nil {
		t.Fatal(err)
	}
	agentPaths, err := agentruntime.Resolve(root, root)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.MkdirAll(filepath.Dir(agentPaths.Socket), 0700); err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen("unix", agentPaths.Socket)
	if err != nil {
		t.Fatal(err)
	}
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Roami-Owner") != "local" {
			t.Error("missing owner binding")
		}
		handler(w, r)
	})}
	go server.Serve(listener)
	t.Cleanup(func() { server.Close() })
	return runtime.Runtime{HomeDir: root, DataDir: root}
}
func apiReply(w http.ResponseWriter, data any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"data": data})
}
func commandResult(t *testing.T, rt runtime.Runtime, args ...string) string {
	t.Helper()
	var output bytes.Buffer
	if err := runCommand(context.Background(), rt, args, &output, strings.NewReader("")); err != nil {
		t.Fatal(err)
	}
	return output.String()
}
func TestHelpCannotDispatchOrResolveRuntime(t *testing.T) {
	for _, args := range [][]string{{"help"}, {"help", "member"}, {"new", "anything", "--help"}, {"member", "add", fixtureID, "--help"}, {"pause", fixtureID, "--help"}, {"chat", "--help"}} {
		output := commandResult(t, runtime.Runtime{}, args...)
		if !strings.Contains(output, "roami swarm") || !strings.Contains(output, "\n用法\n") {
			t.Fatalf("incomplete help: %s", output)
		}
	}
}
func TestBoardAndCollectionKeepReportsSeparateFromVerification(t *testing.T) {
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" || r.URL.Path != "/v1/swarms/"+fixtureID {
			t.Errorf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		apiReply(w, collaborationFixture())
	})
	output := commandResult(t, rt, "board", fixtureID, "--json")
	var board struct {
		Data struct {
			Columns map[string][]workItem `json:"columns"`
		} `json:"data"`
	}
	if err := json.Unmarshal([]byte(output), &board); err != nil {
		t.Fatal(err)
	}
	if len(board.Data.Columns["done"]) != 1 || board.Data.Columns["done"][0].Member != "api" || board.Data.Columns["review"][0].Member != "ui" {
		t.Fatalf("verification bypass: %s", output)
	}
	output = commandResult(t, rt, "collect", fixtureID, "--json")
	var result struct {
		Data struct{ Verified, Pending []workItem } `json:"data"`
	}
	_ = json.Unmarshal([]byte(output), &result)
	if len(result.Data.Verified) != 1 || result.Data.Verified[0].Member != "api" || len(result.Data.Pending) != 2 {
		t.Fatalf("unverified report collected as success: %s", output)
	}
}
func TestMembersAndWorkUseActualTaskAndRun(t *testing.T) {
	paths := []string{}
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		paths = append(paths, r.URL.Path)
		if strings.HasPrefix(r.URL.Path, "/v1/tasks/") {
			apiReply(w, map[string]any{"task": map[string]any{"id": "task-api", "revision": 2}, "artifacts": []any{map[string]any{"id": "artifact-current"}}})
			return
		}
		apiReply(w, collaborationFixture())
	})
	members := commandResult(t, rt, "members", fixtureID)
	if !strings.Contains(members, "task-api") || !strings.Contains(members, "Roami") {
		t.Fatal(members)
	}
	detail := commandResult(t, rt, "member", "show", fixtureID, "api", "--json")
	if !strings.Contains(detail, "artifact-current") || !strings.Contains(detail, "run-api") {
		t.Fatal(detail)
	}
	if paths[len(paths)-1] != "/v1/tasks/task-api" {
		t.Fatal(paths)
	}
}
func TestDirectMutationsPreserveKeysAndRevision(t *testing.T) {
	for _, action := range []string{"pause", "resume", "stop", "archive"} {
		t.Run(action, func(t *testing.T) {
			calls := 0
			rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
				calls++
				if r.Method != "POST" || !strings.HasSuffix(r.URL.Path, "/control") {
					t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
				}
				var body map[string]any
				_ = json.NewDecoder(r.Body).Decode(&body)
				if !reflect.DeepEqual(body, map[string]any{"commandKey": "stable-key", "expectedRevision": float64(4), "action": action}) {
					t.Errorf("changed command identity: %#v", body)
				}
				apiReply(w, map[string]any{"id": fixtureID, "revision": 5})
			})
			commandResult(t, rt, action, fixtureID, "--key", "stable-key", "--revision", "4", "--json")
			if calls != 1 {
				t.Fatal("control performed an extra read/write", calls)
			}
		})
	}
}
func TestMemberPlanAndPinnedArtifactDependencies(t *testing.T) {
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "/plan") {
			t.Error(r.URL.Path)
		}
		var body struct {
			CommandKey       string
			ExpectedRevision int
			Items            []struct {
				Executor     string
				Integration  bool
				Dependencies []dependency
			}
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body.CommandKey != "member-1" || body.ExpectedRevision != 4 || len(body.Items) != 1 || body.Items[0].Executor != "native" || !body.Items[0].Integration || body.Items[0].Dependencies[0].ArtifactID != "artifact-2" || body.Items[0].Dependencies[0].Revision != 2 {
			t.Errorf("wrong plan: %#v", body)
		}
		apiReply(w, map[string]any{"id": fixtureID, "revision": 5})
	})
	commandResult(t, rt, "member", "add", fixtureID, "integrate", "--executor", "roami", "--goal", "验收上游", "--acceptance", "验证产物", "--key", "member-1", "--revision", "4", "--depends-on", "api@2#artifact-2", "--integration")
}
func TestMemberReplyRetainsExplicitRevisionAcrossRetries(t *testing.T) {
	current := collaborationFixture()
	bodies := []map[string]any{}
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "GET" {
			apiReply(w, current)
			return
		}
		if !strings.HasSuffix(r.URL.Path, "/messages") {
			t.Error(r.URL.Path)
		}
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		bodies = append(bodies, body)
		apiReply(w, map[string]any{"operationId": "op-existing"})
	})
	args := []string{"say", fixtureID, "修改接口", "--to", "api", "--task-revision", "2", "--key", "reply-1"}
	commandResult(t, rt, args...)
	current.Work[0].Revision = 3
	commandResult(t, rt, args...)
	if len(bodies) != 2 || !reflect.DeepEqual(bodies[0], bodies[1]) || bodies[1]["taskRevision"] != float64(2) || bodies[1]["workId"] != "work-api" {
		t.Fatalf("retry changed original task/revision: %#v", bodies)
	}
}
func TestDependencyRepairRequiresExplicitClear(t *testing.T) {
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "GET" {
			apiReply(w, collaborationFixture())
			return
		}
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body["workId"] != "work-check" || len(body["dependencies"].([]any)) != 0 {
			t.Error(body)
		}
		apiReply(w, map[string]any{"revision": 5})
	})
	commandResult(t, rt, "dependencies", fixtureID, "check", "--clear", "--key", "clear-1", "--revision", "4")
}
func TestFileInputAndPrivateMemberPost(t *testing.T) {
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "/member-posts") {
			t.Error(r.URL.Path)
		}
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body["taskId"] != "task-api" || body["runId"] != "run-api" || body["taskRevision"] != float64(2) {
			t.Error(body)
		}
		apiReply(w, map[string]any{"id": 2})
	})
	var output bytes.Buffer
	body := `{"commandKey":"post-1","text":"准备验收","taskId":"task-api","runId":"run-api","taskRevision":2}`
	if err := runCommand(context.Background(), rt, []string{"post", fixtureID, "--file", "-", "--json"}, &output, strings.NewReader(body)); err != nil {
		t.Fatal(err)
	}
	commandResult(t, rt, "post", fixtureID, "--help", "--json")
}
func TestInvalidInputsNeverReachRuntime(t *testing.T) {
	cases := [][]string{
		{"ls", "--typo"}, {"status", fixtureID, "extra"}, {"say", fixtureID, "text", "--to", "api", "--key", "message"},
		{"member", "add", fixtureID, "api", "--executor", "unknown", "--goal", "g", "--acceptance", "a", "--key", "k", "--revision", "4"},
		{"pause", fixtureID, "--key", "k", "--revision", "0"}, {"pause", fixtureID, "--key", "one", "--key", "two", "--revision", "4"},
		{"plan", fixtureID}, {"dependencies", fixtureID, "check", "--key", "k", "--revision", "4"},
	}
	for _, args := range cases {
		var output bytes.Buffer
		err := runCommand(context.Background(), runtime.Runtime{}, args, &output, strings.NewReader(""))
		if err == nil {
			t.Errorf("invalid command accepted: %v", args)
		}
		if strings.Contains(fmt.Sprint(err), "storage-layout") {
			t.Errorf("invalid request touched runtime before validation: %v: %v", args, err)
		}
	}
	for _, body := range []string{"null", "[]", "{}", `{"commandKey":"k","expectedRevision":0}`, `{"commandKey":"k","expectedRevision":2.2}`} {
		var output bytes.Buffer
		err := runCommand(context.Background(), runtime.Runtime{}, []string{"plan", fixtureID, "--file", "-"}, &output, strings.NewReader(body))
		if err == nil || strings.Contains(fmt.Sprint(err), "storage-layout") {
			t.Errorf("invalid file reached runtime: %s %v", body, err)
		}
	}
}
func TestSSEFollowUsesSequenceAndExitsOnCancellation(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "/events") {
			apiReply(w, collaborationFixture())
			return
		}
		if r.URL.Query().Get("after") != "10" || r.Header.Get("Accept") != "text/event-stream" {
			t.Error("lost sequence", r.URL.String())
		}
		value := collaborationFixture()
		value.Sequence = 11
		value.Posts = append(value.Posts, post{ID: 2, Author: "main", Text: "NEW_MESSAGE", CreatedMS: 22})
		raw, _ := json.Marshal(value)
		event, _ := json.Marshal(snapshotEvent{ID: 11, Kind: "swarm.snapshot", Payload: raw})
		w.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprintf(w, "data: %s\n\ndata: %s\n\n", event, event)
		w.(http.Flusher).Flush()
		<-r.Context().Done()
	})
	writer := &cancelWriter{cancel: cancel, marker: "NEW_MESSAGE"}
	err := runCommand(ctx, rt, []string{"chat", fixtureID, "--follow", "--json"}, writer, strings.NewReader(""))
	if err != nil {
		t.Fatal(err)
	}
	if strings.Count(writer.String(), "NEW_MESSAGE") != 1 || !strings.Contains(writer.String(), "VERIFIED_RESULT") {
		t.Fatal(writer.String())
	}
}

type cancelWriter struct {
	bytes.Buffer
	cancel context.CancelFunc
	marker string
}

func (w *cancelWriter) Write(p []byte) (int, error) {
	n, err := w.Buffer.Write(p)
	if strings.Contains(w.String(), w.marker) {
		w.cancel()
	}
	return n, err
}
func TestSSEParserIgnoresReplaysAndRejectsWrongGroup(t *testing.T) {
	value := collaborationFixture()
	raw, _ := json.Marshal(value)
	event, _ := json.Marshal(snapshotEvent{ID: 11, Kind: "swarm.snapshot", Payload: raw})
	cursor := int64(10)
	calls := 0
	err := consumeSnapshots(strings.NewReader(": heartbeat\n\ndata: "+string(event)+"\n\ndata: "+string(event)+"\n\n"), &cursor, fixtureID, func(snapshot, snapshotEvent) error { calls++; return nil })
	if err != io.EOF || calls != 1 || cursor != 11 {
		t.Fatal(err, calls, cursor)
	}
	cursor = 10
	if err = consumeSnapshots(strings.NewReader("data: "+string(event)+"\n\n"), &cursor, "other", func(snapshot, snapshotEvent) error { return nil }); err == nil || cursor != 10 {
		t.Fatal("wrong-group event advanced cursor", err, cursor)
	}
}

func TestSSEReconnectPreservesCursorAndDeduplicatesMessages(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	queries := make(chan string, 10)
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "/events") {
			apiReply(w, collaborationFixture())
			return
		}
		after := r.URL.Query().Get("after")
		queries <- after
		w.Header().Set("Content-Type", "text/event-stream")
		value := collaborationFixture()
		value.Posts = append(value.Posts, post{ID: 2, Author: "main", Text: "FIRST_DELIVERY", CreatedMS: 22})
		emit := func(id int64) {
			raw, _ := json.Marshal(value)
			event, _ := json.Marshal(snapshotEvent{ID: id, Kind: "swarm.snapshot", Payload: raw})
			fmt.Fprintf(w, "data: %s\n\n", event)
			w.(http.Flusher).Flush()
		}
		emit(11)
		if after == "10" {
			return
		}
		if after != "11" {
			t.Error("lost reconnect cursor", after)
		}
		value.Posts = append(value.Posts, post{ID: 3, Author: "main", Text: "AFTER_RECONNECT", CreatedMS: 23})
		emit(12)
		<-r.Context().Done()
	})
	writer := &cancelWriter{cancel: cancel, marker: "AFTER_RECONNECT"}
	if err := runCommand(ctx, rt, []string{"chat", fixtureID, "--follow", "--json"}, writer, strings.NewReader("")); err != nil {
		t.Fatal(err)
	}
	if strings.Count(writer.String(), "FIRST_DELIVERY") != 1 || strings.Count(writer.String(), "AFTER_RECONNECT") != 1 {
		t.Fatal(writer.String())
	}
	if len(queries) != 2 {
		t.Fatal("unexpected reconnect count", len(queries))
	}
	if <-queries != "10" || <-queries != "11" {
		t.Fatal("cursor not retained")
	}
}
func TestPrivateMemberPostFlagsCarryActualRunBinding(t *testing.T) {
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "/member-posts") {
			t.Error(r.URL.Path)
		}
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body["taskId"] != "task-api" || body["runId"] != "run-api" || body["taskRevision"] != float64(2) || body["text"] != "--help" {
			t.Error(body)
		}
		apiReply(w, map[string]any{"id": 2})
	})
	commandResult(t, rt, "post", fixtureID, "--key", "note", "--task", "task-api", "--run", "run-api", "--task-revision", "2", "--", "--help")
}
func TestRequestFilesRejectOversizedAndMixedInputs(t *testing.T) {
	if _, err := readRequest("-", strings.NewReader(strings.Repeat(" ", 1<<20)+"{}")); err == nil || !strings.Contains(err.Error(), "TOO_LARGE") {
		t.Fatal(err)
	}
	var output bytes.Buffer
	if err := runCommand(context.Background(), runtime.Runtime{}, []string{"member", "add", fixtureID, "--file", "-", "--integration"}, &output, strings.NewReader(`{"commandKey":"p","expectedRevision":1,"items":[]}`)); err == nil || !strings.Contains(err.Error(), "do not mix") {
		t.Fatal(err)
	}
}

func TestBoardFollowJSONHasSameColumnContractAsSnapshot(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt := fixtureRuntime(t, func(w http.ResponseWriter, r *http.Request) { apiReply(w, collaborationFixture()) })
	writer := &cancelWriter{cancel: cancel, marker: "work-api"}
	if err := runCommand(ctx, rt, []string{"board", fixtureID, "--follow", "--json"}, writer, strings.NewReader("")); err != nil {
		t.Fatal(err)
	}
	var event struct {
		Kind string `json:"kind"`
		Data struct {
			Columns map[string][]workItem `json:"columns"`
		} `json:"data"`
	}
	if err := json.Unmarshal(writer.Bytes(), &event); err != nil {
		t.Fatal(err)
	}
	if event.Kind != "swarm.board" || len(event.Data.Columns["done"]) != 1 || len(event.Data.Columns["review"]) != 1 {
		t.Fatal(writer.String())
	}
}
func TestDependencyCannotSilentlyDropAnEmptyArtifactPin(t *testing.T) {
	options, err := parseOptions([]string{"--depends-on", "api@2#"}, "depends-on", "")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = dependencyFlags(options); err == nil {
		t.Fatal("empty artifact binding was accepted")
	}
}
