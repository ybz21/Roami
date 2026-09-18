// Package sdk is the plugin-side runtime for builtin (Go) plugins: it speaks
// framed JSON-RPC on stdio with the host and exposes typed platform-API
// wrappers (对应 docs/design/plugin/09 的 @roam/plugin-sdk,Go 版).
package sdk

import (
	"encoding/json"
	"fmt"
	"os"
	"time"

	"ttmux-cli-go/internal/plugin/rpc"
)

// CommandHandler serves one contributed command; args are the parsed CLI
// key-value flags. Return value is the structured command result.
type CommandHandler func(ctx *Ctx, args map[string]string) (any, error)

// EventHandler serves one host-dispatched event type.
type EventHandler func(ctx *Ctx, payload json.RawMessage) error

// Plugin is what a builtin implementation registers at activation.
type Plugin struct {
	Commands map[string]CommandHandler // key = bare handler name (无插件前缀)
	Events   map[string]EventHandler   // key = event type,如 "notification"
}

// Ctx is the plugin's view of the host (typed wrappers over roam/* calls).
type Ctx struct {
	PluginID   string
	Workspace  string
	StorageDir string
	Locale     string
	Config     map[string]string

	conn *rpc.Conn
}

// Logf writes to stderr — 宿主把 stderr 收集到 plugins/logs/<id>.log。
func (c *Ctx) Logf(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "[%s] %s\n", c.PluginID, fmt.Sprintf(format, args...))
}

func (c *Ctx) call(method string, params any, out any, timeout time.Duration) error {
	if c.conn == nil {
		return fmt.Errorf("sdk: no host connection (offline ctx)")
	}
	raw, err := c.conn.Call(method, params, timeout)
	if err != nil {
		return err
	}
	if out == nil {
		return nil
	}
	return json.Unmarshal(raw, out)
}

// ── typed platform API ──

// DiffResult mirrors roam/workspace.diff.
type DiffResult struct {
	Branch string `json:"branch"`
	Stat   string `json:"stat"`
	Diff   string `json:"diff"`
}

// WorkspaceDiff returns the reviewable diff; dir 为空时用宿主注入的工作区。
func (c *Ctx) WorkspaceDiff(dir string) (DiffResult, error) {
	var out DiffResult
	err := c.call("roam/workspace.diff", map[string]string{"dir": dir}, &out, 60*time.Second)
	return out, err
}

func (c *Ctx) AgentProviders() (map[string]bool, error) {
	out := map[string]bool{}
	err := c.call("roam/agent.providers", nil, &out, 15*time.Second)
	return out, err
}

// SpawnReq mirrors roam/agent.spawn.
type SpawnReq struct {
	Provider    string            `json:"provider,omitempty"`
	Prompt      string            `json:"prompt"`
	SessionName string            `json:"sessionName"`
	Workdir     string            `json:"workdir,omitempty"`
	Job         string            `json:"job,omitempty"`
	Labels      map[string]string `json:"labels,omitempty"`
	Interactive bool              `json:"interactive,omitempty"` // 交互 TUI(可持续对话)
}

func (c *Ctx) AgentSpawn(req SpawnReq) (session string, err error) {
	var out struct {
		Session string `json:"session"`
	}
	err = c.call("roam/agent.spawn", req, &out, 60*time.Second)
	return out.Session, err
}

// AgentRunResult mirrors roam/agent.run.
type AgentRunResult struct {
	Exit     int    `json:"exit"`
	Output   string `json:"output"`
	Provider string `json:"provider"`
}

// AgentRun executes a one-shot agent as a blocking host subprocess(不占
// 会话名、不进会话列表;适合审查类短时机器工作)。
func (c *Ctx) AgentRun(provider, prompt, workdir string, timeoutSec int) (AgentRunResult, error) {
	var out AgentRunResult
	if timeoutSec <= 0 {
		timeoutSec = 1800
	}
	err := c.call("roam/agent.run", map[string]any{
		"provider": provider, "prompt": prompt, "workdir": workdir, "timeoutSec": timeoutSec,
	}, &out, time.Duration(timeoutSec+60)*time.Second)
	return out, err
}

// SessionWait blocks until the session exits (host-side long call).
func (c *Ctx) SessionWait(name string, timeoutSec int) (bool, error) {
	var out struct {
		Done bool `json:"done"`
	}
	err := c.call("roam/session.wait", map[string]any{"name": name, "timeoutSec": timeoutSec},
		&out, time.Duration(timeoutSec+30)*time.Second)
	return out.Done, err
}

// SessionAlive reports whether the tmux session still exists。必须走宿主的
// session.alive 真实判定:capture 探测在会话消亡后会退回读日志"成功"返回,
// 导致陪跑 watch 永远等不到退出信号。
func (c *Ctx) SessionAlive(name string) bool {
	var out struct {
		Alive bool `json:"alive"`
	}
	if err := c.call("roam/session.alive", map[string]string{"name": name}, &out, 15*time.Second); err != nil {
		return false
	}
	return out.Alive
}

// SessionKill terminates a session owned by this plugin(spawn/track 登记过
// 的才允许;管家 graceful recycle 的兜底手段)。
func (c *Ctx) SessionKill(name string) error {
	return c.call("roam/session.kill", map[string]string{"name": name}, nil, 15*time.Second)
}

// SessionCapture returns the last tailLines of the session pane.
func (c *Ctx) SessionCapture(name string, tailLines int) (string, error) {
	var out struct {
		Output string `json:"output"`
	}
	err := c.call("roam/session.capture", map[string]any{"name": name, "tailLines": tailLines}, &out, 30*time.Second)
	return out.Output, err
}

// SessionSend types text + Enter into a session(需 sessions:write)。
func (c *Ctx) SessionSend(name, text string) error {
	return c.call("roam/session.send", map[string]string{"name": name, "text": text}, nil, 30*time.Second)
}

// StorageGet reads the plugin's private KV(缺省为空串)。
func (c *Ctx) StorageGet(key string) (string, error) {
	var out struct {
		Value string `json:"value"`
	}
	err := c.call("roam/storage.get", map[string]string{"key": key}, &out, 15*time.Second)
	return out.Value, err
}

// StorageSet writes the plugin's private KV(空值即删除)。
func (c *Ctx) StorageSet(key, value string) error {
	return c.call("roam/storage.set", map[string]string{"key": key, "value": value}, nil, 15*time.Second)
}

// SessionInfo mirrors the host's plugin session row (roam/session.list)。
type SessionInfo struct {
	Session string            `json:"session"`
	Job     string            `json:"job"`
	Labels  map[string]string `json:"labels"`
	Status  string            `json:"status"`
	Created string            `json:"created"`
}

// SessionList returns this plugin's owned sessions (spawn/track 登记的)。
func (c *Ctx) SessionList() ([]SessionInfo, error) {
	var out []SessionInfo
	err := c.call("roam/session.list", map[string]string{}, &out, 30*time.Second)
	return out, err
}

// AllSession 是本机一条会话的概览(roam/session.listAll)。与 SessionList 的
// 区别:那个只给本插件 spawn/track 过的会话,这个给**所有**会话——守护/巡检类
// 插件要看的正是别人建的那些。
type AllSession struct {
	Session  string `json:"session"`  // 会话 id(改名不变,拿它当主键)
	Label    string `json:"label"`    // 展示名(会变,只配拿来显示)
	Agent    string `json:"agent"`    // claude | codex | ""(认不出)
	Dir      string `json:"dir"`      // 归属目录
	Attached bool   `json:"attached"` // 此刻有人 attach 着
	Activity int64  `json:"activity"` // 最后一次有动静(unix 秒)
	IdleSec  int64  `json:"idleSec"`  // 安静了多久(秒)
	Created  int64  `json:"created"`
}

// SessionListAll returns every session on this machine (需 sessions:read)。
// 基础设施会话(_ttmux-*)由宿主过滤掉。
func (c *Ctx) SessionListAll() ([]AllSession, error) {
	var out []AllSession
	err := c.call("roam/session.listAll", map[string]string{}, &out, 30*time.Second)
	return out, err
}

func (c *Ctx) SessionLog(name string) (string, error) {
	var out struct {
		Log string `json:"log"`
	}
	err := c.call("roam/session.log", map[string]string{"name": name}, &out, 30*time.Second)
	return out.Log, err
}

// ExecResult mirrors roam/command.exec.
type ExecResult struct {
	Exit   int    `json:"exit"`
	Output string `json:"output"`
}

func (c *Ctx) CommandExec(argv []string, timeoutSec int) (ExecResult, error) {
	var out ExecResult
	err := c.call("roam/command.exec", map[string]any{"argv": argv, "timeoutSec": timeoutSec},
		&out, time.Duration(timeoutSec+30)*time.Second)
	return out, err
}

// Finding mirrors the host finding model.
type Finding struct {
	ID       int64  `json:"id,omitempty"`
	Job      string `json:"job,omitempty"`
	Severity string `json:"severity"`
	Title    string `json:"title"`
	File     string `json:"file,omitempty"`
	Line     int    `json:"line,omitempty"`
	Detail   string `json:"detail,omitempty"`
	Status   string `json:"status,omitempty"`
}

func (c *Ctx) FindingCreate(f Finding) (int64, error) {
	var out struct {
		ID int64 `json:"id"`
	}
	err := c.call("roam/finding.create", f, &out, 30*time.Second)
	return out.ID, err
}

func (c *Ctx) FindingList(job, status string) ([]Finding, error) {
	var out []Finding
	err := c.call("roam/finding.list", map[string]string{"job": job, "status": status}, &out, 30*time.Second)
	return out, err
}

// Notification mirrors roam/notification.publish.
type Notification struct {
	Type      string `json:"type"`
	Severity  string `json:"severity,omitempty"`
	Title     string `json:"title"`
	Body      string `json:"body,omitempty"`
	DedupeKey string `json:"dedupeKey,omitempty"`
}

func (c *Ctx) NotificationPublish(n Notification) error {
	return c.call("roam/notification.publish", n, nil, 120*time.Second)
}

// ── serve loop ──

// Serve runs the plugin main loop on stdio. activate 构造 handler 表;
// 之后进程被动等待宿主派发,deactivate 后返回。
func Serve(activate func(ctx *Ctx) Plugin) {
	ctx := &Ctx{}
	var impl Plugin
	done := make(chan struct{})
	handler := func(method string, params json.RawMessage) (any, error) {
		switch method {
		case "initialize":
			var init struct {
				PluginID   string            `json:"pluginId"`
				Workspace  string            `json:"workspace"`
				StorageDir string            `json:"storageDir"`
				Locale     string            `json:"locale"`
				Config     map[string]string `json:"config"`
			}
			if err := json.Unmarshal(params, &init); err != nil {
				return nil, err
			}
			ctx.PluginID, ctx.Workspace, ctx.StorageDir = init.PluginID, init.Workspace, init.StorageDir
			ctx.Locale, ctx.Config = init.Locale, init.Config
			impl = activate(ctx)
			names := make([]string, 0, len(impl.Commands))
			for name := range impl.Commands {
				names = append(names, name)
			}
			return map[string]any{"commands": names}, nil
		case "plugin/invokeCommand":
			var req struct {
				Command string            `json:"command"`
				Args    map[string]string `json:"args"`
			}
			if err := json.Unmarshal(params, &req); err != nil {
				return nil, err
			}
			h, ok := impl.Commands[req.Command]
			if !ok {
				return nil, &rpc.Error{Code: rpc.CodeUnknownMethod, Message: "unknown command: " + req.Command}
			}
			return h(ctx, req.Args)
		case "plugin/onEvent":
			var req struct {
				Type    string          `json:"type"`
				Payload json.RawMessage `json:"payload"`
			}
			if err := json.Unmarshal(params, &req); err != nil {
				return nil, err
			}
			h, ok := impl.Events[req.Type]
			if !ok {
				return map[string]bool{"handled": false}, nil
			}
			if err := h(ctx, req.Payload); err != nil {
				return nil, err
			}
			return map[string]bool{"handled": true}, nil
		case "plugin/deactivate":
			defer close(done)
			return map[string]bool{"ok": true}, nil
		}
		return nil, &rpc.Error{Code: rpc.CodeUnknownMethod, Message: "unknown method: " + method}
	}
	conn := rpc.NewConn(os.Stdin, os.Stdout, handler)
	ctx.conn = conn
	select {
	case <-done:
		time.Sleep(50 * time.Millisecond) // 让 deactivate 响应发出去
	case <-conn.Done():
	}
}
