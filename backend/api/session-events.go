package api

// 会话事件（24 稿 §6）：把 tmux 里看得见的三件事变成通知——
//   session.waiting  屏上出现等你的选择框（抓屏，连续两轮为真才发；回到不等就复位）
//   session.done     Claude 一轮说完了（转录最后一条 assistant 是 end_turn 且不在等你）
//   session.error    agent 进程没了、屏上还留着报错
// 5s 一轮；启动那一轮只登记不发（进程一重启就把早已在等的再推一遍是噪音）。
// event → 收件箱落库 + Web Push 广播。

import (
	"bytes"
	"encoding/json"
	"os"
	"regexp"
	"strings"
	"time"
)

type sessionEventState struct {
	streak   int
	notified bool
	lastTurn string // 已经通知过的那条 end_turn 的 uuid
	hadAgent bool
}

// lastTurnInfo 转录里最后一条 assistant 的摘要；没有就 key 为空
type lastTurnInfo struct {
	key  string
	stop string // end_turn | tool_use | …
	text string
	at   time.Time
}

type sessionEvents struct {
	state  map[string]sessionEventState
	seeded bool
}

func newSessionEvents() *sessionEvents { return &sessionEvents{state: map[string]sessionEventState{}} }

var yesNoPat = regexp.MustCompile(`(?i)\((?:y/n|yes/no|y/N|Y/n)\)|\[y/n\]`)
var yesFirst = regexp.MustCompile(`(?i)^(yes|allow|approve|ok|continue|proceed|是|允许|确认|继续)\b`)
var errorTail = regexp.MustCompile(`(?i)\b(error|panic|fatal|killed|failed|traceback)\b|exit (?:status |code )?[1-9]|已终止|错误`)

// observeInput 一轮观察的原料，全部由调用方给（便于测试）
type observeInput struct {
	sessions map[string]string              // 活会话 name → label
	capture  func(name string) string       // 抓屏
	agents   map[string]bool                // 这一轮哪些会话里跑着 agent
	lastTurn func(name string) lastTurnInfo // Claude 转录最后一条 assistant
}

func (e *sessionEvents) observe(in observeInput) []PushPayload {
	var out []PushPayload
	for name := range e.state {
		if _, ok := in.sessions[name]; !ok {
			delete(e.state, name)
		}
	}
	for name, label := range in.sessions {
		cap := in.capture(name)
		st := e.state[name]
		waiting := sessionWaiting(cap)

		// ── 等你 ──
		if !waiting {
			st.streak, st.notified = 0, false
		} else {
			st.streak++
			if !e.seeded {
				st.streak, st.notified = 2, true
			}
			if st.streak >= 2 && !st.notified {
				st.notified = true
				p := PushPayload{Type: "session.waiting", Session: name, Label: label, Title: label, Body: waitingSummary(cap, 140)}
				if _, opts, ok := waitingPrompt(cap); (ok && len(opts) > 0 && yesFirst.MatchString(opts[0])) || yesNoPat.MatchString(waitStripCtl(cap)) {
					p.Actions = []string{"allow", "deny"}
				}
				out = append(out, p)
			}
		}

		// ── 做完了：Claude 转录最后一条 assistant 是 end_turn。在等你的不算（那是问题，上面已经发过）──
		if in.lastTurn != nil {
			lt := in.lastTurn(name)
			if lt.key != "" && lt.key != st.lastTurn {
				if lt.stop == "end_turn" && !waiting && e.seeded && time.Since(lt.at) < 10*time.Minute {
					out = append(out, PushPayload{Type: "session.done", Session: name, Label: label, Title: label, Body: oneLine(lt.text, 140)})
				}
				st.lastTurn = lt.key
			}
		}

		// ── 出错了：上一轮有 agent、这一轮没了，屏上还留着报错 ──
		has := in.agents[name]
		if st.hadAgent && !has && e.seeded {
			tail := sessionTail(cap, 140)
			if errorTail.MatchString(waitStripCtl(cap)) {
				out = append(out, PushPayload{Type: "session.error", Session: name, Label: label, Title: label, Body: tail})
			}
		}
		st.hadAgent = has
		e.state[name] = st
	}
	e.seeded = true
	return out
}

// oneLine 通知正文：去掉 markdown 换行和标题符，截到 max 个字
func oneLine(s string, max int) string {
	s = strings.NewReplacer("\n", " ", "\r", " ", "**", "", "`", "").Replace(strings.TrimSpace(s))
	s = strings.Join(strings.Fields(s), " ")
	if r := []rune(s); len(r) > max {
		return string(r[:max]) + "…"
	}
	return s
}

// claudeLastTurn 读转录尾部最后一条 assistant 行。只看末尾 64KB：一行 assistant 通常几 KB。
func claudeLastTurn(file string) lastTurnInfo {
	if file == "" {
		return lastTurnInfo{}
	}
	f, err := os.Open(file)
	if err != nil {
		return lastTurnInfo{}
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return lastTurnInfo{}
	}
	const tailBytes = 64 << 10
	off := st.Size() - tailBytes
	if off < 0 {
		off = 0
	}
	buf := make([]byte, st.Size()-off)
	if _, err := f.ReadAt(buf, off); err != nil && len(buf) == 0 {
		return lastTurnInfo{}
	}
	lines := bytes.Split(buf, []byte("\n"))
	for i := len(lines) - 1; i >= 0; i-- {
		l := bytes.TrimSpace(lines[i])
		if len(l) == 0 || !bytes.Contains(l, []byte(`"type":"assistant"`)) {
			continue
		}
		var row struct {
			Type      string `json:"type"`
			UUID      string `json:"uuid"`
			Timestamp string `json:"timestamp"`
			Message   struct {
				StopReason string `json:"stop_reason"`
				Content    []struct {
					Type string `json:"type"`
					Text string `json:"text"`
				} `json:"content"`
			} `json:"message"`
		}
		if json.Unmarshal(l, &row) != nil || row.Type != "assistant" {
			continue
		}
		var texts []string
		for _, b := range row.Message.Content {
			if b.Type == "text" && b.Text != "" {
				texts = append(texts, b.Text)
			}
		}
		at, _ := time.Parse(time.RFC3339Nano, row.Timestamp)
		return lastTurnInfo{key: row.UUID, stop: row.Message.StopReason, text: strings.Join(texts, " "), at: at}
	}
	return lastTurnInfo{}
}

// SessionEventLoop 后台探测循环
func (a *API) SessionEventLoop() {
	ev := newSessionEvents()
	t := time.NewTicker(5 * time.Second)
	defer t.Stop()
	// 转录文件按 (会话, pid) 缓存：pickTranscript 要扫目录，不必每 5s 扫一遍
	type fileKey struct {
		name string
		pid  int
	}
	files := map[fileKey]string{}
	for range t.C {
		if a.Push.Count() == 0 && !a.Meta.OK() {
			continue // 没人订阅也没处落，白抓屏
		}
		out, err := a.TT.Run("ls", "--json")
		if err != nil {
			continue
		}
		var list []sessListItem
		if json.Unmarshal([]byte(out), &list) != nil {
			continue
		}
		sessions := map[string]string{}
		for _, s := range list {
			if s.State == "dormant" || strings.HasPrefix(s.Name, "_ttmux-") {
				continue
			}
			label := s.Label
			if label == "" {
				label = s.Name
			}
			sessions[s.Name] = label
		}
		procs := runningAgentProcs()
		agents := map[string]bool{}
		for name, p := range procs {
			agents[name] = p.Kind == "claude" || p.Kind == "codex"
		}
		lastTurn := func(name string) lastTurnInfo {
			p, ok := procs[name]
			if !ok || p.Kind != "claude" {
				return lastTurnInfo{}
			}
			k := fileKey{name, p.Pid}
			file, cached := files[k]
			if !cached {
				file = pickTranscript(projectDirFor(p.Dir), procArgvOf(p.Pid), procStartOf(p.Pid))
				if file != "" {
					files[k] = file
				}
			}
			return claudeLastTurn(file)
		}
		for _, p := range ev.observe(observeInput{sessions: sessions, capture: func(n string) string { return sessionCapture(n, 60) }, agents: agents, lastTurn: lastTurn}) {
			p.ID = a.Inbox.Publish(p.Type, p.Session, p.Label, p.Body)
			p.Badge = a.Inbox.Unread()
			a.Push.Broadcast(p)
		}
		for k := range files { // 进程换了就丢缓存
			if p, ok := procs[k.name]; !ok || p.Pid != k.pid {
				delete(files, k)
			}
		}
	}
}
