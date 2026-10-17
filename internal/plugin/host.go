package plugin

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"github.com/ybz21/Roami/internal/plugin/rpc"
)

// InitContext is what the host injects into a plugin at initialize
// (docs/design/plugin/09 §5).
type InitContext struct {
	PluginID   string            `json:"pluginId"`
	Workspace  string            `json:"workspace"`
	StorageDir string            `json:"storageDir"`
	Locale     string            `json:"locale"`
	Config     map[string]string `json:"config"`
}

// Hosted is a running plugin subprocess with its RPC connection.
type Hosted struct {
	Plugin RegisteredPlugin
	cmd    *exec.Cmd
	conn   *rpc.Conn
	logF   *os.File
}

// StartPlugin launches the plugin subprocess and completes the initialize
// handshake. 三种运行时形态在宿主眼里协议一致(04-architecture 第 3 节):
// builtin 以自身二进制的隐藏子命令 _plugin-host 拉起;node 用 node 解释
// main;exec 直接执行 main(需可执行位)。
// depth 是通知级联深度:sink 插件以 depth=1 托管,其自身 publish 不再分发。
// termStderr 时插件 stderr 直通调用方终端(plugin run 的"面板即界面",
// 如 watch 陪跑会话的进度日志);否则收集到 plugins/logs/<id>.log。
func StartPlugin(env Env, store *Store, p RegisteredPlugin, actor, workdir string, depth int, termStderr bool) (*Hosted, error) {
	var cmd *exec.Cmd
	switch p.Manifest.Runtime.Kind {
	case "builtin":
		self, err := os.Executable()
		if err != nil {
			return nil, err
		}
		cmd = exec.Command(self, "_plugin-host", p.Manifest.ID)
	case "node", "exec":
		if p.InstallPath == "" {
			return nil, fmt.Errorf("plugin %s has no install path (reinstall with: roami plugin install <dir|tgz>)", p.Manifest.ID)
		}
		mainPath := filepath.Join(p.InstallPath, filepath.Clean("/"+p.Manifest.Main)) // 防越出安装目录
		if _, err := os.Stat(mainPath); err != nil {
			return nil, fmt.Errorf("plugin %s main not found: %s", p.Manifest.ID, mainPath)
		}
		if p.Manifest.Runtime.Kind == "node" {
			nodeBin, err := exec.LookPath("node")
			if err != nil {
				return nil, fmt.Errorf("plugin %s needs Node.js but node is not in PATH", p.Manifest.ID)
			}
			cmd = exec.Command(nodeBin, mainPath)
		} else {
			cmd = exec.Command(mainPath)
		}
		cmd.Dir = p.InstallPath
	default:
		return nil, fmt.Errorf("unsupported runtime.kind %q for plugin %s", p.Manifest.Runtime.Kind, p.Manifest.ID)
	}
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	var logF *os.File
	if termStderr {
		cmd.Stderr = os.Stderr // 面板即界面:进度直接可见
	} else {
		logPath := filepath.Join(env.LogsDir(), p.Manifest.ID+".log")
		f, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err == nil {
			logF = f
			cmd.Stderr = logF // 插件日志走 stderr,宿主收集(stdout 只走 RPC)
		}
	}
	if err := cmd.Start(); err != nil {
		if logF != nil {
			logF.Close()
		}
		return nil, err
	}
	api := &HostAPI{Env: env, Store: store, Plugin: p, Actor: actor, Workdir: workdir, dispatchDepth: depth}
	conn := rpc.NewConn(stdout, stdin, api.Handle)
	h := &Hosted{Plugin: p, cmd: cmd, conn: conn, logF: logF}

	cfg, _ := env.LoadConfig(p.Manifest.ID)
	initCtx := InitContext{
		PluginID:   p.Manifest.ID,
		Workspace:  workdir,
		StorageDir: env.StorageDir(p.Manifest.ID),
		Locale:     "zh-CN",
		Config:     cfg,
	}
	if _, err := conn.Call("initialize", initCtx, 10*time.Second); err != nil {
		h.Close()
		return nil, fmt.Errorf("plugin %s failed to initialize: %w", p.Manifest.ID, err)
	}
	return h, nil
}

// Invoke runs a contributed command inside the plugin. Commands are short
// transactions;长活由插件经 agent.spawn 转成会话(handler 内可等待)。
func (h *Hosted) Invoke(handler string, args map[string]string, timeout time.Duration) (json.RawMessage, error) {
	return h.conn.Call("plugin/invokeCommand", map[string]any{"command": handler, "args": args}, timeout)
}

// SendEvent delivers an event (notification, session exit, ...) to the plugin.
func (h *Hosted) SendEvent(eventType string, payload any, timeout time.Duration) error {
	_, err := h.conn.Call("plugin/onEvent", map[string]any{"type": eventType, "payload": payload}, timeout)
	return err
}

// Close deactivates the plugin gracefully, then reaps the process (超时 5s
// 后 SIGKILL,见 04-architecture 生命周期兜底).
func (h *Hosted) Close() {
	if h.conn != nil {
		_, _ = h.conn.Call("plugin/deactivate", map[string]string{"reason": "done"}, 2*time.Second)
		h.conn.Close()
	}
	if h.cmd != nil && h.cmd.Process != nil {
		done := make(chan struct{})
		go func() { _, _ = h.cmd.Process.Wait(); close(done) }()
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			_ = h.cmd.Process.Kill()
		}
	}
	if h.logF != nil {
		h.logF.Close()
	}
}

// ProtoErrors surfaces framing violations for health accounting.
func (h *Hosted) ProtoErrors() int64 { return h.conn.ProtoErrors() }

// DispatchToSinks activates every enabled sink plugin matching the
// notification type and delivers it as an event. Returns delivered count.
// 插件之间不直连:级联只经宿主、只一层(见 04-architecture 铁律 3)。
func DispatchToSinks(env Env, store *Store, n Notification, depth int) int {
	all, err := store.List()
	if err != nil {
		return 0
	}
	delivered := 0
	for _, p := range all {
		if !p.Enabled || p.Manifest.ID == n.Source || !p.Manifest.SinkMatches(n.Type) {
			continue
		}
		actor := "plugin:" + n.Source
		h, err := StartPlugin(env, store, p, actor, ".", depth, false)
		if err != nil {
			fmt.Fprintf(os.Stderr, "[plugin] sink %s activation failed: %v\n", p.Manifest.ID, err)
			continue
		}
		if err := h.SendEvent("notification", n, 60*time.Second); err != nil {
			fmt.Fprintf(os.Stderr, "[plugin] sink %s delivery failed: %v\n", p.Manifest.ID, err)
		} else {
			delivered++
		}
		h.Close()
	}
	return delivered
}
