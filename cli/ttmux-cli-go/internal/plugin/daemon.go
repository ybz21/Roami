package plugin

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"time"

	"ttmux-cli-go/internal/plugin/rpc"
	"ttmux-cli-go/internal/runtime"
)

// DaemonSession is the tmux session hosting plugind(项目习惯:长驻负载进
// tmux,可 attach 看日志;见 04-architecture 4.2)。
const DaemonSession = "_ttmux-plugind"

// IMListenerSession hosts the im-bridge long-connection listener
// (入站 @机器人 派活;由 plugind 托管:配置齐且插件启用时自动拉起,掉了重拉)。
const IMListenerSession = "_ttmux-im"

// KeepaliveSession hosts the session-guard sweep loop(roam.keepalive:
// 屏幕太久没动就替人催一句)。同样由 plugind 托管——用户在设置页打开一个
// 开关,东西就该真的跑起来,而不是再去装一个 systemd timer。
const KeepaliveSession = "_ttmux-keepalive"

// RunDaemonForeground runs plugind: a unix-socket control API plus the
// session watcher that synthesizes agent.exited events for plugin-owned
// sessions (spawn 时 wait=false 的异步收尾路径)。
func RunDaemonForeground(env Env) error {
	store, err := Open(env)
	if err != nil {
		return err
	}
	defer store.Close()
	if err := SyncBuiltins(store); err != nil {
		return err
	}

	sock := env.SockPath()
	// stale socket 清理:能 ping 通说明已有实例,拒绝双开;否则移除残留。
	if pingSock(sock) {
		return fmt.Errorf("plugind already running on %s", sock)
	}
	_ = os.Remove(sock)
	ln, err := net.Listen("unix", sock)
	if err != nil {
		return err
	}
	defer ln.Close()
	defer os.Remove(sock)
	_ = os.Chmod(sock, 0o600)
	fmt.Printf("[plugind] listening on %s\n", sock)

	go acceptLoop(ln, env, store)

	reconcileStale(env, store)
	ticker := time.NewTicker(3 * time.Second)
	defer ticker.Stop()
	for range ticker.C {
		watchOnce(env, store)
		ensureIMListener(env, store)
		ensureKeepaliveLoop(env, store)
	}
	return nil
}

// lastIMStart throttles listener restarts(凭据错误时长连接秒退,不能 3s
// 一循环地锤 IM 鉴权接口;冷却 60s,配置修好后最多一分钟内自愈)。
var lastIMStart time.Time

// ensureIMListener keeps the im-bridge inbound listener session alive when
// the plugin is enabled and provider credentials are configured. `plugin run`
// 的 invoke 上限 24h,监听会话日级回收后由这里重拉,天然自愈。
func ensureIMListener(env Env, store *Store) {
	if env.RT.HasSession(IMListenerSession) {
		return
	}
	if time.Since(lastIMStart) < time.Minute {
		return
	}
	p, err := store.Get("roam.im-bridge")
	if err != nil || !p.Enabled {
		return
	}
	cfg, err := env.LoadConfig(p.Manifest.ID)
	if err != nil {
		return
	}
	// provider 凭据齐了才拉(目前:feishu 需 app_id/app_secret;其余 provider
	// 尚未实现,不自动拉起)
	prov := cfg["im_provider"]
	if prov != "" && prov != "feishu" {
		return
	}
	if cfg["app_id"] == "" || cfg["app_secret"] == "" {
		return
	}
	self, err := os.Executable()
	if err != nil {
		return
	}
	lastIMStart = time.Now()
	if err := env.RT.Tmux("new-session", "-d", "-s", IMListenerSession, self+" plugin run im-bridge.listen"); err != nil {
		fmt.Fprintf(os.Stderr, "[plugind] im listener start failed: %v\n", err)
		return
	}
	fmt.Printf("[plugind] im listener started in session %s\n", IMListenerSession)
}

// ensureKeepaliveLoop keeps the session-guard sweep loop alive while the
// plugin has something to guard. `plugin run` 的 invoke 上限 24h,循环会话
// 日级回收后由这里重拉,天然自愈——和 IM 长连接同一个机制。
//
// 「有没有活要干」由**插件自己举手**:它在私有 storage 里写 wanted=1。宿主只
// 读这一个键,不去解析守护表——插件的数据结构是插件的家事。守护表空了循环会
// 自己退出(见 plugins/keepalive/watch.go 的 serve),这里也就不会再拉。
func ensureKeepaliveLoop(env Env, store *Store) {
	if env.RT.HasSession(KeepaliveSession) {
		return
	}
	if time.Since(lastKeepaliveStart) < keepaliveCooldown {
		return
	}
	p, err := store.Get("roam.keepalive")
	if err != nil || !p.Enabled {
		return
	}
	if env.LoadStorage(p.Manifest.ID)["wanted"] != "1" {
		return
	}
	self, err := os.Executable()
	if err != nil {
		return
	}
	lastKeepaliveStart = time.Now()
	if err := env.RT.Tmux("new-session", "-d", "-s", KeepaliveSession, self+" plugin run keepalive.serve"); err != nil {
		fmt.Fprintf(os.Stderr, "[plugind] keepalive loop start failed: %v\n", err)
		return
	}
	fmt.Printf("[plugind] keepalive loop started in session %s\n", KeepaliveSession)
}

// lastKeepaliveStart 节流重拉。冷却比 IM 那条短得多(10s 对 60s):这里没有
// 外部接口可锤,循环退出多半是因为守护表空了,而用户刚打开一个开关时不该等一分钟。
var lastKeepaliveStart time.Time

const keepaliveCooldown = 10 * time.Second

// reconcileStale settles sessions that died while plugind was down. reviewer
// 会话照常派发收尾(解析日志落 findings 迟到也有价值);review:auto 的开发
// 会话只静默标记——隔了半天再凭空拉起一个"兜底互审"reviewer 会话,就是
// 用户看到的"多余的死会话"。
func reconcileStale(env Env, store *Store) {
	rows, err := store.Sessions("", "running")
	if err != nil {
		return
	}
	for _, r := range rows {
		if env.RT.HasSession(r.Session) {
			continue
		}
		_ = store.UpdateSessionStatus(r.Session, "exited")
		if r.Labels["role"] == "reviewer" {
			fmt.Printf("[plugind] stale reviewer session %s; finalizing\n", r.Session)
			dispatch(env, store, r, "session:agent.exited")
		} else {
			fmt.Printf("[plugind] session %s died while plugind was down; skipping stale event\n", r.Session)
		}
		_ = store.UpdateSessionStatus(r.Session, "handled")
	}
}

func acceptLoop(ln net.Listener, env Env, store *Store) {
	for {
		conn, err := ln.Accept()
		if err != nil {
			return
		}
		go func(c net.Conn) {
			defer c.Close()
			r := rpc.NewConn(c, c, func(method string, params json.RawMessage) (any, error) {
				switch method {
				case "daemon/ping":
					return map[string]any{"ok": true, "pid": os.Getpid(), "version": runtime.Version}, nil
				case "daemon/status":
					plugins, _ := store.List()
					running, _ := store.Sessions("", "running")
					enabled := 0
					for _, p := range plugins {
						if p.Enabled {
							enabled++
						}
					}
					return map[string]any{
						"pid": os.Getpid(), "plugins": len(plugins), "enabled": enabled,
						"watchedSessions": len(running),
					}, nil
				}
				return nil, &rpc.Error{Code: rpc.CodeUnknownMethod, Message: "unknown method: " + method}
			})
			<-r.Done()
		}(conn)
	}
}

// watchOnce marks exited plugin sessions and dispatches session:agent.exited
// to the owner plugin(事件合成:tmux 会话列表 diff,见 04-architecture 6.1)。
// "对话空闲即互审"不在这里做——那由 review-mesh 的监控会话陪跑实现,
// 可见可 attach(review-mesh.watch)。
func watchOnce(env Env, store *Store) {
	rows, err := store.Sessions("", "running")
	if err != nil {
		return
	}
	for _, r := range rows {
		if env.RT.HasSession(r.Session) {
			continue
		}
		_ = store.UpdateSessionStatus(r.Session, "exited")
		fmt.Printf("[plugind] session %s exited; notifying %s\n", r.Session, r.Plugin)
		dispatch(env, store, r, "session:agent.exited")
		_ = store.UpdateSessionStatus(r.Session, "handled")
	}
}

// dispatch activates the owner plugin and delivers one event.
func dispatch(env Env, store *Store, r SessionRow, eventType string) {
	owner, err := store.Get(r.Plugin)
	if err != nil || !owner.Enabled {
		return
	}
	h, err := StartPlugin(env, store, owner, "watcher:plugind", ".", 0, false)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[plugind] activate %s failed: %v\n", r.Plugin, err)
		return
	}
	defer h.Close()
	if err := h.SendEvent(eventType, r, 120*time.Second); err != nil {
		fmt.Fprintf(os.Stderr, "[plugind] %s delivery to %s failed: %v\n", eventType, r.Plugin, err)
	}
}

// pingSock dials the control socket and pings the daemon.
func pingSock(sock string) bool {
	conn, err := net.DialTimeout("unix", sock, time.Second)
	if err != nil {
		return false
	}
	defer conn.Close()
	c := rpc.NewConn(conn, conn, nil)
	defer c.Close()
	_, err = c.Call("daemon/ping", nil, 2*time.Second)
	return err == nil
}

// DaemonStatus queries the daemon; returns nil map when not running.
func DaemonStatus(env Env) map[string]any {
	sock := env.SockPath()
	conn, err := net.DialTimeout("unix", sock, time.Second)
	if err != nil {
		return nil
	}
	defer conn.Close()
	c := rpc.NewConn(conn, conn, nil)
	defer c.Close()
	raw, err := c.Call("daemon/status", nil, 2*time.Second)
	if err != nil {
		return nil
	}
	out := map[string]any{}
	_ = json.Unmarshal(raw, &out)
	return out
}

// EnsureDaemon starts plugind inside its tmux session when not reachable.
// 健康判定顺序:connect+ping → tmux 会话校验 → stale 清理 → 拉起
// (docs/design/plugin/04 4.2;文件锁在 tmux has-session/new-session 的原子性
// 下由 tmux 代劳)。
func EnsureDaemon(env Env) error {
	if pingSock(env.SockPath()) {
		return nil
	}
	rt := env.RT
	if rt.HasSession(DaemonSession) {
		// 会话在但 ping 不通:视为 stale,杀掉重拉
		_ = rt.Tmux("kill-session", "-t", DaemonSession)
	}
	_ = os.Remove(env.SockPath())
	self, err := os.Executable()
	if err != nil {
		return err
	}
	if err := rt.Tmux("new-session", "-d", "-s", DaemonSession, self+" plugin daemon --foreground"); err != nil {
		return err
	}
	for i := 0; i < 20; i++ {
		time.Sleep(250 * time.Millisecond)
		if pingSock(env.SockPath()) {
			return nil
		}
	}
	return fmt.Errorf("plugind did not become healthy (inspect: ttmux a %s)", DaemonSession)
}
