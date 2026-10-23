package api

import (
	"database/sql"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestCodexCompletionEvent(t *testing.T) {
	path := filepath.Join(t.TempDir(), "rollout.jsonl")
	line := `{"timestamp":"2026-10-22T07:00:00Z","type":"event_msg","payload":{"type":"task_complete","turn_id":"turn-1","last_agent_message":"任务完成"}}`
	if err := os.WriteFile(path, []byte(line+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	got := codexLastTurn(path)
	if got.key != "turn-1" || got.stop != "end_turn" || got.text != "任务完成" || got.at.IsZero() {
		t.Fatalf("Codex 完成事件解析错误: %+v", got)
	}
}

func TestCodexCompletionSurvivesLargeFollowingToolOutput(t *testing.T) {
	path := filepath.Join(t.TempDir(), "rollout.jsonl")
	completed := `{"timestamp":"2026-10-22T07:00:00Z","type":"event_msg","payload":{"type":"task_complete","turn_id":"turn-1","last_agent_message":"已修复上传失败，并通过构建验证。"}}`
	following := `{"type":"response_item","payload":{"type":"function_call_output","output":"` + strings.Repeat("x", 128<<10) + `"}}`
	if err := os.WriteFile(path, []byte(completed+"\n"+following+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	got := codexLastTurn(path)
	if got.key != "turn-1" || !strings.Contains(got.text, "上传失败") {
		t.Fatalf("lost completion after tool output: %+v", got)
	}
}

func TestOpenCodeCompletionEvent(t *testing.T) {
	db, err := sql.Open("sqlite", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err := db.Exec(`CREATE TABLE session_message (id TEXT, session_id TEXT, type TEXT, seq INTEGER, data TEXT)`); err != nil {
		t.Fatal(err)
	}
	insert := func(id string, seq int, finish string, completed int64) {
		t.Helper()
		data := `{"finish":"` + finish + `","time":{"completed":` + strconv.FormatInt(completed, 10) + `},"content":[{"type":"text","text":"任务完成"}]}`
		if _, err := db.Exec(`INSERT INTO session_message VALUES (?, 'session-1', 'assistant', ?, ?)`, id, seq, data); err != nil {
			t.Fatal(err)
		}
	}
	insert("message-1", 1, "tool-calls", time.Now().UnixMilli())
	insert("message-2", 2, "", 0)
	if got := openCodeLastTurn(db, "session-1"); got.key != "" {
		t.Fatalf("流式消息不应发完成提醒: %+v", got)
	}
	if _, err := db.Exec(`DELETE FROM session_message WHERE id='message-2'`); err != nil {
		t.Fatal(err)
	}
	insert("message-3", 3, "stop", time.Now().UnixMilli())
	got := openCodeLastTurn(db, "session-1")
	if got.key != "message-3" || got.stop != "end_turn" || got.text != "任务完成" {
		t.Fatalf("OpenCode 完成事件解析错误: %+v", got)
	}
}

const waitScreen = "Do you want to proceed?\n❯ 1. Yes\n  2. No\nEnter to select · Esc to cancel"

func inputOf(sessions map[string]string, screen string) observeInput {
	return observeInput{sessions: sessions, capture: func(string) string { return screen }, agents: map[string]bool{}}
}

func TestSessionEventsDebounceAndReset(t *testing.T) {
	ev := newSessionEvents()
	ev.observe(inputOf(map[string]string{}, "")) // 启动那一轮：只登记
	sess := map[string]string{"s1": "调研"}
	if got := ev.observe(inputOf(sess, waitScreen)); len(got) != 0 {
		t.Fatalf("第一轮不该发（残帧）: %+v", got)
	}
	got := ev.observe(inputOf(sess, waitScreen))
	if len(got) != 1 || got[0].Type != "session.waiting" || got[0].Session != "s1" || got[0].Label != "调研" {
		t.Fatalf("第二轮该发一条: %+v", got)
	}
	if len(got[0].Actions) != 2 {
		t.Fatalf("1. Yes 这种该带 允许/拒绝: %+v", got[0])
	}
	if got[0].Body != "Do you want to proceed?\n1. Yes\n2. No" {
		t.Fatalf("正文该是问题加选项: %q", got[0].Body)
	}
	if got := ev.observe(inputOf(sess, waitScreen)); len(got) != 0 {
		t.Fatalf("同一次等待不该重复发: %+v", got)
	}
	ev.observe(inputOf(sess, "$ "))
	ev.observe(inputOf(sess, waitScreen))
	if got := ev.observe(inputOf(sess, waitScreen)); len(got) != 1 {
		t.Fatalf("复位后再等该再发: %+v", got)
	}
	ev.observe(inputOf(map[string]string{}, waitScreen))
	if len(ev.state) != 0 {
		t.Fatalf("会话没了状态该清: %+v", ev.state)
	}
}

// 进程重启：启动时就在等的会话不再推一遍
func TestSessionEventsSeedOnStart(t *testing.T) {
	ev := newSessionEvents()
	sess := map[string]string{"s1": "早就在等"}
	for i := 0; i < 3; i++ {
		if got := ev.observe(inputOf(sess, waitScreen)); len(got) != 0 {
			t.Fatalf("启动前就在等的不该推: %+v", got)
		}
	}
	ev.observe(inputOf(sess, "$ "))
	ev.observe(inputOf(sess, waitScreen))
	if got := ev.observe(inputOf(sess, waitScreen)); len(got) != 1 {
		t.Fatalf("复位后再等该推: %+v", got)
	}
}

func TestSessionEventsNoActionsForFreeChoice(t *testing.T) {
	ev := newSessionEvents()
	ev.observe(inputOf(map[string]string{}, ""))
	sess := map[string]string{"s": "x"}
	screen := "选一个\n❯ 1. 按周\n  2. 按月\n  3. 自定义\nEnter to select"
	ev.observe(inputOf(sess, screen))
	got := ev.observe(inputOf(sess, screen))
	if len(got) != 1 || len(got[0].Actions) != 0 {
		t.Fatalf("三选一不该带 允许/拒绝: %+v", got)
	}
}

// 做完了：新的 end_turn 才发一次；tool_use 不算；在等你的不算；启动时已有的不算
func TestSessionEventsDone(t *testing.T) {
	ev := newSessionEvents()
	sess := map[string]string{"s": "周报"}
	turn := lastTurnInfo{key: "u1", stop: "end_turn", text: "**做完了**\n\n改了三处", at: time.Now()}
	in := func(screen string, lt lastTurnInfo) observeInput {
		i := inputOf(sess, screen)
		i.agents = map[string]bool{"s": true}
		i.lastTurn = func(string) lastTurnInfo { return lt }
		return i
	}
	if got := ev.observe(in("$ ", turn)); len(got) != 0 {
		t.Fatalf("启动那一轮已有的 end_turn 不该推: %+v", got)
	}
	if got := ev.observe(in("$ ", turn)); len(got) != 0 {
		t.Fatalf("同一条不该再推: %+v", got)
	}
	turn2 := lastTurnInfo{key: "u2", stop: "tool_use", text: "", at: time.Now()}
	if got := ev.observe(in("$ ", turn2)); len(got) != 0 {
		t.Fatalf("tool_use 不算做完: %+v", got)
	}
	turn3 := lastTurnInfo{key: "u3", stop: "end_turn", text: "**做完了**\n\n改了三处", at: time.Now()}
	got := ev.observe(in("$ ", turn3))
	if len(got) != 1 || got[0].Type != "session.done" || got[0].Body != "做完了 改了三处" {
		t.Fatalf("新 end_turn 该推一条 done，正文去掉 markdown: %+v", got)
	}
	turn4 := lastTurnInfo{key: "u4", stop: "end_turn", text: "要不要继续？", at: time.Now()}
	ev.observe(in(waitScreen, turn4))
	if got := ev.observe(in(waitScreen, turn4)); len(got) != 1 || got[0].Type != "session.waiting" {
		t.Fatalf("在等你时的 end_turn 只发 waiting 不发 done: %+v", got)
	}
}

// 出错了：agent 没了且屏上有报错才算；正常退出不算
func TestSessionEventsError(t *testing.T) {
	ev := newSessionEvents()
	sess := map[string]string{"s": "x"}
	withAgent := inputOf(sess, "working…")
	withAgent.agents = map[string]bool{"s": true}
	ev.observe(withAgent)
	ev.observe(withAgent)
	gone := inputOf(sess, "panic: runtime error\n$ ")
	if got := ev.observe(gone); len(got) != 1 || got[0].Type != "session.error" {
		t.Fatalf("agent 没了且有报错该推 error: %+v", got)
	}
	ev.observe(withAgent)
	clean := inputOf(sess, "bye\n$ ")
	if got := ev.observe(clean); len(got) != 0 {
		t.Fatalf("正常退出不该推: %+v", got)
	}
}

func TestSessionTailSkipsSpinnerAndPromptLines(t *testing.T) {
	cap := "● 构建跑完了，三个包都过了。\n\n✻ Improvising… (19m 35s · ↓ 15.6k tokens)\n\n❯ 看下构建跑完没有\n────────\n  ⏵⏵ auto mode on\n"
	if got := sessionTail(cap, 80); got != "● 构建跑完了，三个包都过了。" {
		t.Fatalf("tail = %q", got)
	}
}

func TestScreenBusyOnlyLooksAtBottomAndIgnoresDoneSummary(t *testing.T) {
	done := "● 好了。\n\n✻ Crunched for 17s · done 22:50\n\n❯ \n────\n  ⏵⏵ auto mode on\n"
	if screenBusy(done) {
		t.Fatal("干完的小结不该算在跑")
	}
	if got := sessionTail(done, 80); got != "● 好了。" {
		t.Fatalf("tail = %q", got)
	}
	old := "(esc to interrupt)\n" + strings.Repeat("一行输出\n", 20) + "❯ \n"
	if screenBusy(old) {
		t.Fatal("滚动区里的旧状态行不该算在跑")
	}
	if !screenBusy("● 在改\n\n✻ Improvising… (19m 35s · ↓ 15.6k tokens)\n\n❯ \n") {
		t.Fatal("转圈那行应该算在跑")
	}
	if got := sessionTail("● 跑测试\n  (ctrl+b ctrl+b (twice) to run in background)\n", 80); got != "● 跑测试" {
		t.Fatalf("tail = %q", got)
	}
}

func TestSessionTailSkipsDoneSummaryVariants(t *testing.T) {
	for _, chrome := range []string{"✻ Brewed for 2m 35s · done 20:00", "✻ Cogitated for 4m 48s · done 1:32", "  1: Bad    2: Fine   3: Good   0: Dismiss", "1 to review · 2 to send · 0 to dismiss", "  ⎿  Interrupted · What should Claude do instead?"} {
		if got := sessionTail("● 真正的最后一句\n\n"+chrome+"\n", 80); got != "● 真正的最后一句" {
			t.Fatalf("%q 没被跳过，tail = %q", chrome, got)
		}
	}
}
