package session

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/ybz21/Roami/internal/sessionstore"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

type sessionInfo struct {
	// Name tmux 会话名 = 会话 id（新会话），也是所有 API/WS 的 handle。
	Name string `json:"name"`
	// Label 展示名（tmux 用户选项 @roam_name）：用户起的名字，可改、可重复，
	// 只用于展示（前端渲染成「名字（id）」）。没设过则回退成会话名。
	Label string `json:"label,omitempty"`
	// ID 可读会话 id（2026-0728-1150-0142）：会话名本身就是它；迁移前的老会话
	// 由 session_created + session_id 现算派生，与 TmuxID 一一对应。
	ID string `json:"id,omitempty"`
	// TmuxID 原始 #{session_id}（$142）：内部键（meta.db 主键、session-homes 的键）。
	TmuxID       string `json:"tmux_id,omitempty"`
	Windows      int    `json:"windows"`
	Created      string `json:"created"`
	Attached     int    `json:"attached"`
	LastActivity string `json:"last_activity"`
	// State 是会话的「在」与「活」：live = tmux 里真的有；dormant = 台账里还认得它，
	// 机器重启带走了 tmux 那一半，点开即恢复。前端据此渲染，也据此决定标签留不留。
	State string `json:"state,omitempty"`
	// Agent 这个会话跑的是哪种 agent（claude / codex），空 = 不是 agent 会话。
	Agent string `json:"agent,omitempty"`
	// Resumable 休眠会话点开后能不能连对话一起接回（有 agent 对话 id）。
	Resumable bool `json:"resumable,omitempty"`
	// Dir 归属目录。休眠会话在列表里得靠它认人——很多老会话连展示名都没有。
	Dir string `json:"dir,omitempty"`
	// Repo 所属仓库根，建会话时就算好落进台账的。休眠会话没有 tmux 句柄，
	// 项目归属算不出来（Annotations 那条路只认活会话），只能靠这一列——
	// 少了它，重启后所有会话都掉进「散会话·不属于任何项目」。
	Repo string `json:"repo,omitempty"`
	// Mem 这个会话此刻吃了多少（字节）。休眠会话没有进程，恒为 nil。
	Mem *memInfo `json:"mem,omitempty"`
	// 下面两列供 ls --tree 建父子投影，平铺输出时省略。
	Parent    string `json:"parent,omitempty"`
	CreatedBy string `json:"created_by,omitempty"`
}

// memInfo 会话内存画像。Limit=0 表示没设上限（护栏关掉或装不上）。
type memInfo struct {
	Cur   int64 `json:"cur"`
	Peak  int64 `json:"peak,omitempty"`
	Limit int64 `json:"limit,omitempty"`
}

type infoJSON struct {
	Version  string `json:"version"`
	Tmux     string `json:"tmux_version"`
	DataDir  string `json:"data_dir"`
	Sessions int    `json:"sessions"`
	Groups   int    `json:"groups"`
}

func ListJSON(rt runtime.Runtime, meta *sessmeta.Store, exclude map[string]bool, w io.Writer) error {
	return json.NewEncoder(w).Encode(Collect(rt, meta, exclude))
}

func InfoJSON(rt runtime.Runtime, version string, exclude map[string]bool, w io.Writer) error {
	sessions := 0
	for _, name := range rt.Sessions() {
		if !exclude[name] {
			sessions++
		}
	}
	groups := 0
	matches, _ := filepath.Glob(filepath.Join(rt.GroupsDir, "*.group"))
	groups = len(matches)
	tmuxVersion := strings.TrimSpace(must(rt.TmuxOutput("-V")))
	return json.NewEncoder(w).Encode(infoJSON{
		Version:  version,
		Tmux:     strings.TrimPrefix(tmuxVersion, "tmux "),
		DataDir:  rt.DataDir,
		Sessions: sessions,
		Groups:   groups,
	})
}

func Capture(rt runtime.Runtime, args []string, w io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: roami session capture <session> [--lines N]")
	}
	target := rt.Resolve(args[0])
	lines := "200"
	for i := 1; i < len(args); i++ {
		switch args[i] {
		case "--lines", "-n":
			if i+1 < len(args) {
				lines = args[i+1]
				i++
			}
		}
	}
	if _, err := strconv.Atoi(lines); err != nil {
		return fmt.Errorf("invalid line count: %s", lines)
	}
	out, err := rt.ReadCapture(target, lines)
	if err != nil {
		return err
	}
	_, err = io.WriteString(w, out)
	if err == nil && !strings.HasSuffix(out, "\n") {
		_, err = io.WriteString(w, "\n")
	}
	return err
}

// Resolve 处理 `roami session resolve <会话名|id|展示名> [--json]`：把任意 token 解析成
// tmux 会话名（= 会话 id）。后端与外部脚本靠它把用户输入/老书签换算成 handle。
func Resolve(rt runtime.Runtime, args []string, w io.Writer) error {
	var token string
	for _, a := range args {
		if !strings.HasPrefix(a, "--") && token == "" {
			token = a
		}
	}
	if token == "" {
		return fmt.Errorf("usage: roami session resolve <会话名|id|展示名> [--json]")
	}
	name := rt.Resolve(token)
	if !rt.HasSession(name) {
		return fmt.Errorf("session not found: %s", token)
	}
	if has(args, "--json") {
		row := rt.SessionRow(name)
		return json.NewEncoder(w).Encode(map[string]string{
			"name": row.Name, "label": row.DisplayLabel(), "id": row.ID(), "tmux_id": row.TmuxID,
		})
	}
	_, err := io.WriteString(w, name+"\n")
	return err
}

func must(s string, _ error) string {
	return s
}

// maxNumeric returns whichever of two tmux epoch strings is the larger number,
// tolerating empty/garbage (parses as 0). Keeps the string form for the JSON.
func maxNumeric(a, b string) string {
	na, _ := strconv.ParseInt(strings.TrimSpace(a), 10, 64)
	nb, _ := strconv.ParseInt(strings.TrimSpace(b), 10, 64)
	if nb > na {
		return b
	}
	return a
}

func IsTerminal() bool {
	info, err := os.Stdout.Stat()
	return err == nil && info.Mode()&os.ModeCharDevice != 0
}

// Session is the structured list result used by both public adapters.
type Session = sessionInfo
