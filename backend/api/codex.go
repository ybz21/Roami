// Codex 集成：检测会话是否在跑 codex（OpenAI Codex CLI），并把其会话记录(rollout JSONL)
// 解析成可渲染的对话。机制与 claude.go 一致——只「读」记录渲染，「发」消息复用 ttmux send。
//
// rollout 文件位于 ~/.codex/sessions/YYYY/MM/DD/rollout-<时间>-<uuid>.jsonl。
// 每行一个 JSON：response_item 承载对话主体（message/reasoning/function_call/...），
// event_msg 多为重复或噪声（仅 mcp_tool_call_end 无 response_item 对应，单独渲染）。
package api

import (
	"bufio"
	"encoding/json"
	"io/fs"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
)

// cmdlineHasCodex 判断进程命令行是否是交互式 codex CLI。
// 排除 codex-web（ttmux 自身）、mcp-server（Claude Code 会把 codex 当 MCP server 启动）、
// app-server（Codex 桌面端/VS Code 插件的后台服务）。
func cmdlineHasCodex(pid int) bool { return argvIsCodex(processArgv(pid)) }

func codexSessionsRoot() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".codex", "sessions")
}

// listRollouts 返回所有 rollout-*.jsonl，按修改时间倒序（活跃会话排最前）。
func listRollouts() []string {
	root := codexSessionsRoot()
	type fm struct {
		path string
		mod  int64
	}
	var all []fm
	filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return nil
		}
		if !strings.HasPrefix(d.Name(), "rollout-") || !strings.HasSuffix(d.Name(), ".jsonl") {
			return nil
		}
		if info, e := d.Info(); e == nil {
			all = append(all, fm{p, info.ModTime().UnixNano()})
		}
		return nil
	})
	sort.Slice(all, func(i, j int) bool { return all[i].mod > all[j].mod })
	out := make([]string, len(all))
	for i, x := range all {
		out[i] = x.path
	}
	return out
}

// rolloutCwd 读取 rollout 首行 session_meta 的 cwd。
func rolloutCwd(path string) string {
	f, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1024*1024), 8*1024*1024)
	if sc.Scan() {
		var raw struct {
			Type    string `json:"type"`
			Payload struct {
				Cwd string `json:"cwd"`
			} `json:"payload"`
		}
		if json.Unmarshal(sc.Bytes(), &raw) == nil && raw.Type == "session_meta" {
			return raw.Payload.Cwd
		}
	}
	return ""
}

// newestCodexRollout 选 cwd 匹配且最近修改的 rollout；无匹配则退回最近修改的（多半即活跃会话）。
func newestCodexRollout(cwd string) string {
	files := listRollouts()
	if len(files) == 0 {
		return ""
	}
	for i, p := range files {
		if i >= 200 { // 仅在最近的若干个里找匹配，避免遍历历史全量
			break
		}
		if rolloutCwd(p) == cwd {
			return p
		}
	}
	return files[0]
}

// CodexStatus GET /sessions/:name/codex —— 检测会话是否在跑 codex，并定位其 rollout。
// 如果某个 pane 的进程树同时命中 claude，说明 codex 是 Claude Code 的子进程，不算独立运行。
func (a *API) CodexStatus(c *gin.Context) {
	name := a.sessionTarget(c)
	out, err := exec.Command("tmux", "list-panes", "-t", name, "-F", "#{pane_pid}\t#{pane_current_path}").Output()
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"running": false}})
		return
	}
	children := procChildren()
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		parts := strings.SplitN(line, "\t", 2)
		if len(parts) != 2 {
			continue
		}
		pid, err := strconv.Atoi(parts[0])
		if err != nil {
			continue
		}
		if treeMatch(pid, children, 0, cmdlineHasClaude) {
			continue
		}
		if treeMatch(pid, children, 0, cmdlineHasCodex) {
			dir := parts[1]
			c.JSON(http.StatusOK, gin.H{"data": gin.H{"running": true, "dir": dir, "file": newestCodexRollout(dir)}})
			return
		}
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"running": false}})
}

// ── rollout JSONL → 可渲染对话（复用 claude.go 的 cBlock/cMsg/clip）──

var codexExitRe = regexp.MustCompile(`(?i)(?:exit code|exited with code):?\s*(\d+)`)

// codexOutputIsError 从工具输出里识别非零退出码。
func codexOutputIsError(s string) bool {
	m := codexExitRe.FindStringSubmatch(s)
	return len(m) == 2 && m[1] != "0"
}

// codexOutputText 把工具输出（字符串或对象）抽成文本。
func codexOutputText(raw json.RawMessage) string {
	if len(raw) == 0 {
		return ""
	}
	var s string
	if json.Unmarshal(raw, &s) == nil {
		return s
	}
	return string(raw)
}

// isCodexContextWrapper 判断用户消息是否为注入的上下文包裹（非用户真实输入），应隐藏。
func isCodexContextWrapper(t string) bool {
	for _, p := range []string{"<environment_context>", "<user_instructions>", "<permissions"} {
		if strings.HasPrefix(t, p) {
			return true
		}
	}
	return false
}

// parseCodexItem 解析 response_item 的 payload。
func parseCodexItem(payload json.RawMessage, ts string) *cMsg {
	var p struct {
		Type    string `json:"type"`
		Role    string `json:"role"`
		Content []struct {
			Text string `json:"text"`
		} `json:"content"`
		Summary []struct {
			Text string `json:"text"`
		} `json:"summary"`
		Name      string          `json:"name"`
		Arguments string          `json:"arguments"`
		Input     string          `json:"input"`
		Output    json.RawMessage `json:"output"`
		CallID    string          `json:"call_id"`
	}
	if json.Unmarshal(payload, &p) != nil {
		return nil
	}
	switch p.Type {
	case "message":
		if p.Role == "developer" { // 系统/权限指令，不展示
			return nil
		}
		var b strings.Builder
		for _, c := range p.Content {
			b.WriteString(c.Text)
		}
		t := strings.TrimSpace(b.String())
		if t == "" {
			return nil
		}
		role := "assistant"
		if p.Role == "user" {
			if isCodexContextWrapper(t) {
				return nil
			}
			role = "user"
		}
		return &cMsg{Role: role, Ts: ts, Blocks: []cBlock{{Kind: "text", Text: clip(t)}}}
	case "reasoning":
		var b strings.Builder
		for _, s := range p.Summary {
			b.WriteString(s.Text)
		}
		t := strings.TrimSpace(b.String())
		if t == "" { // 仅有 encrypted_content、无明文摘要时跳过
			return nil
		}
		return &cMsg{Role: "assistant", Ts: ts, Blocks: []cBlock{{Kind: "thinking", Text: clip(t)}}}
	case "function_call":
		return &cMsg{Role: "assistant", Ts: ts, Blocks: []cBlock{{Kind: "tool_use", Name: p.Name, Input: clip(p.Arguments), ID: p.CallID}}}
	case "custom_tool_call":
		return &cMsg{Role: "assistant", Ts: ts, Blocks: []cBlock{{Kind: "tool_use", Name: p.Name, Input: clip(p.Input), ID: p.CallID}}}
	case "function_call_output", "custom_tool_call_output":
		out := codexOutputText(p.Output)
		return &cMsg{Role: "tool", Ts: ts, Blocks: []cBlock{{Kind: "tool_result", Text: clip(out), ToolUseID: p.CallID, IsError: codexOutputIsError(out)}}}
	}
	return nil
}

// parseCodexEvent 解析 event_msg；仅 mcp_tool_call_end 无 response_item 对应，需在此渲染。
func parseCodexEvent(payload json.RawMessage, ts string) *cMsg {
	var p struct {
		Type       string `json:"type"`
		Invocation struct {
			Server    string          `json:"server"`
			Tool      string          `json:"tool"`
			Arguments json.RawMessage `json:"arguments"`
		} `json:"invocation"`
		Result json.RawMessage `json:"result"`
	}
	if json.Unmarshal(payload, &p) != nil || p.Type != "mcp_tool_call_end" {
		return nil
	}
	name := "mcp:" + p.Invocation.Server + "." + p.Invocation.Tool
	return &cMsg{Role: "tool", Ts: ts, Blocks: []cBlock{
		{Kind: "tool_use", Name: name, Input: clip(string(p.Invocation.Arguments))},
		{Kind: "tool_result", Text: clip(codexOutputText(p.Result))},
	}}
}

// parseCodexLine 把一行 rollout JSONL 解析成 cMsg；非对话行返回 nil。
func parseCodexLine(line string) *cMsg {
	var raw struct {
		Type    string          `json:"type"`
		Ts      string          `json:"timestamp"`
		Payload json.RawMessage `json:"payload"`
	}
	if json.Unmarshal([]byte(line), &raw) != nil {
		return nil
	}
	switch raw.Type {
	case "response_item":
		return parseCodexItem(raw.Payload, raw.Ts)
	case "event_msg":
		return parseCodexEvent(raw.Payload, raw.Ts)
	}
	return nil
}

// scanCodexStatus 从一行 rollout 里更新会话状态。
// Codex 比 Claude 大方：token_count 事件直接把 model_context_window 给出来，
// 不用按模型 id 猜；还额外给了套餐额度（rate_limits），Claude 侧没有这项。
func scanCodexStatus(line string, st cStatus, quota *float64) cStatus {
	var raw struct {
		Type    string          `json:"type"`
		Payload json.RawMessage `json:"payload"`
	}
	if json.Unmarshal([]byte(line), &raw) != nil {
		return st
	}
	switch raw.Type {
	case "turn_context":
		var p struct {
			Model          string `json:"model"`
			Cwd            string `json:"cwd"`
			ApprovalPolicy string `json:"approval_policy"`
			SandboxPolicy  struct {
				Type string `json:"type"`
			} `json:"sandbox_policy"`
			CollaborationMode struct {
				Mode     string `json:"mode"`
				Settings struct {
					ReasoningEffort string `json:"reasoning_effort"`
				} `json:"settings"`
			} `json:"collaboration_mode"`
		}
		if json.Unmarshal(raw.Payload, &p) != nil {
			return st
		}
		if p.Model != "" {
			st.Model = p.Model
		}
		if p.Cwd != "" {
			st.Cwd = p.Cwd
		}
		if e := p.CollaborationMode.Settings.ReasoningEffort; e != "" {
			st.Effort = e
		}
		// 模式取「协作模式」为主（default / plan）；没有就退回沙箱策略，
		// 那至少能回答「它现在能不能动我的盘」这个更要紧的问题。
		if m := p.CollaborationMode.Mode; m != "" {
			st.Mode = m
		} else if p.SandboxPolicy.Type != "" {
			st.Mode = p.SandboxPolicy.Type
		}
	case "event_msg":
		var p struct {
			Type string `json:"type"`
			Info struct {
				Last struct {
					TotalTokens int `json:"total_tokens"`
				} `json:"last_token_usage"`
				Window int `json:"model_context_window"`
			} `json:"info"`
			RateLimits struct {
				Primary struct {
					UsedPercent float64 `json:"used_percent"`
				} `json:"primary"`
			} `json:"rate_limits"`
		}
		if json.Unmarshal(raw.Payload, &p) != nil || p.Type != "token_count" {
			return st
		}
		// total_token_usage 是整场累计值，长会话早就超过上下文窗口。
		if p.Info.Last.TotalTokens > 0 {
			st.Used = p.Info.Last.TotalTokens
		}
		if p.Info.Window > 0 {
			st.Window = p.Info.Window
		}
		if p.RateLimits.Primary.UsedPercent > 0 {
			*quota = p.RateLimits.Primary.UsedPercent
		}
	}
	return st
}

// CodexTranscript GET /sessions/:name/codex-transcript?file=...&offset=N
// 与 ClaudeTranscript 同构：offset 为已消费物理行数，仅返回其后新内容（供增量轮询）。
func (a *API) CodexTranscript(c *gin.Context) {
	file := c.Query("file")
	if file == "" {
		if dir := paneToolDir(a.sessionTarget(c), cmdlineHasCodex); dir != "" {
			file = newestCodexRollout(dir)
		}
	}
	// 同 ClaudeTranscript：还没有 rollout 文件＝agent 刚起，不是坏请求。
	if file == "" {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"messages": []cMsg{}, "nextOffset": 0, "file": ""}})
		return
	}
	// 安全：限制在 ~/.codex/sessions 下
	root := codexSessionsRoot()
	file = filepath.Clean(file)
	if !strings.HasPrefix(file, root) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_FILE"}})
		return
	}
	// offset 是**字节偏移**，见 transcript-read.go（原来是行号，逼着每次轮询
	// 从第 1 行重数一遍，一次请求就分配一整个文件）
	offset, _ := strconv.ParseInt(c.Query("offset"), 10, 64)
	// boff=1 是「我这个 offset 是字节偏移」的标记。没有它就说明对面是**升级前的
	// 页面**，手里攥的还是行号——当字节偏移 seek 会跳到文件很靠前的地方，一次吐回
	// 一大堆重复消息。这时干脆重新锚定到尾部，让它下一轮拿着新语义的游标接着走。
	if offset > 0 && c.Query("boff") != "1" {
		offset = 0
	}

	f, err := os.Open(file)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"messages": []cMsg{}, "nextOffset": 0, "file": file}})
		return
	}
	defer f.Close()

	tail := tailLimit(c, int(offset))
	win := newTranscriptWindow(tail)
	st := cStatus{}
	quota := 0.0

	var lines []transcriptLine
	var size int64
	var more bool
	if offset > 0 {
		if fi, e := f.Stat(); e == nil {
			size = fi.Size()
		}
		if size < offset { // 文件被换过/截断过：从头来
			offset = 0
			lines, size, more, err = readTail(f, tail)
		} else {
			lines, err = readFrom(f, offset, size)
		}
	} else {
		lines, size, more, err = readTail(f, tail*tailLineFactor)
	}
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"messages": []cMsg{}, "nextOffset": offset, "file": file}})
		return
	}
	for _, ln := range lines {
		text := string(ln.Text)
		st = scanCodexStatus(text, st, &quota)
		if m := parseCodexLine(text); m != nil {
			if m.ID == "" { // 行首字节偏移作稳定 key（前端窗口化/折叠态持久化用）
				m.ID = strconv.FormatInt(ln.At, 10)
			}
			win.add(*m)
		}
	}
	if more {
		win.dropped = true
	}
	n := lastComplete(lines, offset)

	msgs, truncated := win.out()
	data := gin.H{"messages": msgs, "nextOffset": n, "file": file, "status": st, "truncated": truncated}
	if quota > 0 {
		data["quota"] = quota
	}
	c.JSON(http.StatusOK, gin.H{"data": data})
}
