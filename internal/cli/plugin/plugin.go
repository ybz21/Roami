// Package plugincmd implements `roami plugin ...` and the hidden
// `_plugin-host` runner(CLI 面见 docs/design/plugin/02-product.md 4.4)。
package plugincmd

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/user"
	"path/filepath"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/plugin"
	"github.com/ybz21/Roami/internal/plugin/builtin"
	"github.com/ybz21/Roami/internal/sessionstore"
	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

// Run dispatches `roami plugin <subcommand>`.
func Run(rt runtime.Runtime, args []string, out io.Writer) error {
	sub := "help"
	if len(args) > 0 {
		sub = args[0]
		args = args[1:]
	}
	env := plugin.NewEnv(rt)
	switch sub {
	case "ls", "list":
		return list(env, args, out)
	case "install":
		return install(env, args, out)
	case "uninstall":
		return uninstall(env, args, out)
	case "restore":
		return restore(env, args, out)
	case "info":
		return info(env, args, out)
	case "enable", "disable":
		return setEnabled(env, sub == "enable", args, out)
	case "run":
		return runCommand(env, args, out)
	case "config":
		return config(env, args, out)
	case "findings":
		return findings(env, args, out)
	case "notifications":
		return notifications(env, args, out)
	case "audit":
		return audit(env, args, out)
	case "status":
		return status(env, args, out)
	case "track":
		return track(env, args, out)
	case "daemon":
		if hasFlag(args, "--foreground") {
			return plugin.RunDaemonForeground(env)
		}
		if err := plugin.EnsureDaemon(env); err != nil {
			return err
		}
		ui.Ok(out, "plugind 已运行(tmux 会话 %s,查看: roami session a %s)", env.HostSession(plugin.DaemonSession), env.HostSession(plugin.DaemonSession))
		return nil
	case "help", "-h", "--help":
		help(out)
		return nil
	}
	return fmt.Errorf("unknown subcommand: plugin %s (see: roami plugin help)", sub)
}

// HostMain runs the hidden `_plugin-host <id>` builtin plugin process.
func HostMain(args []string) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: roami _plugin-host <plugin-id>")
	}
	b, ok := builtin.Find(args[0])
	if !ok {
		return fmt.Errorf("unknown builtin plugin: %s", args[0])
	}
	sdk.Serve(b.Activate)
	return nil
}

func openStore(env plugin.Env) (*plugin.Store, error) {
	store, err := plugin.Open(env)
	if err != nil {
		return nil, err
	}
	if err := plugin.SyncBuiltins(store); err != nil {
		store.Close()
		return nil, err
	}
	return store, nil
}

func list(env plugin.Env, args []string, out io.Writer) error {
	store, err := openStore(env)
	if err != nil {
		return err
	}
	defer store.Close()
	var plugins []plugin.RegisteredPlugin
	if hasFlag(args, "--removed") {
		plugins, err = store.Removed() // 已卸载的内置插件(恢复入口)
	} else {
		plugins, err = store.List()
	}
	if err != nil {
		return err
	}
	if hasFlag(args, "--json") {
		return printJSON(out, plugins)
	}
	for _, p := range plugins {
		state := ui.Dim("disabled")
		if p.Enabled {
			state = "enabled"
		}
		fmt.Fprintf(out, "%-22s %-8s %-9s %s\n", ui.Bold(p.Manifest.Name), p.Manifest.Version, state,
			p.Manifest.Description.Get("zh-CN"))
		for _, c := range p.Manifest.Contributes.Commands {
			fmt.Fprintf(out, "    · roami plugin run %-28s %s\n", c.ID, ui.Dim(c.Title.Get("zh-CN")))
		}
	}
	return nil
}

func info(env plugin.Env, args []string, out io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: roami plugin info <id> [--json]")
	}
	store, err := openStore(env)
	if err != nil {
		return err
	}
	defer store.Close()
	p, err := store.Get(args[0])
	if err != nil {
		return err
	}
	return printJSON(out, p)
}

func setEnabled(env plugin.Env, enabled bool, args []string, out io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: roami plugin enable|disable <id>")
	}
	store, err := openStore(env)
	if err != nil {
		return err
	}
	defer store.Close()
	p, err := store.Get(args[0])
	if err != nil {
		return err
	}
	if err := store.SetEnabled(p.Manifest.ID, enabled); err != nil {
		return err
	}
	verb := "已禁用"
	if enabled {
		verb = "已启用"
	} else {
		// 禁用即停掉该插件的常驻监听会话:ensureIMListener 只在启用时拉起,
		// 不停的话现存监听会一直挂到 24h invoke 上限才退。
		if p.Manifest.ID == "roam.im-bridge" && env.RT.HasSession(plugin.IMListenerSession) {
			_ = env.RT.Tmux("kill-session", "-t", "="+plugin.IMListenerSession)
		}
	}
	ui.Ok(out, "插件 %s %s", ui.Bold(p.Manifest.ID), verb)
	return nil
}

func runCommand(env plugin.Env, args []string, out io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: roami plugin run <plugin>.<command> [--key value ...]")
	}
	commandID := args[0]
	flags := parseFlags(args[1:])
	store, err := openStore(env)
	if err != nil {
		return err
	}
	defer store.Close()
	p, handler, err := store.FindCommand(commandID)
	if err != nil {
		return err
	}
	wd, _ := os.Getwd()
	hosted, err := plugin.StartPlugin(env, store, p, actor(), wd, 0, true)
	if err != nil {
		return err
	}
	defer hosted.Close()
	result, err := hosted.Invoke(handler, flags, 24*time.Hour) // watch 等陪跑型命令可长驻
	if err != nil {
		return err
	}
	return printRaw(out, result)
}

func config(env plugin.Env, args []string, out io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: roami plugin config <id> [set <key> <value> | unset <key>]")
	}
	store, err := openStore(env)
	if err != nil {
		return err
	}
	defer store.Close()
	p, err := store.Get(args[0])
	if err != nil {
		return err
	}
	id := p.Manifest.ID
	cfg, err := env.LoadConfig(id)
	if err != nil {
		return err
	}
	switch {
	case len(args) >= 4 && args[1] == "set":
		cfg[args[2]] = args[3]
		if err := env.SaveConfig(id, cfg); err != nil {
			return err
		}
		ui.Ok(out, "%s.%s 已设置", p.Manifest.Name, args[2])
		return nil
	case len(args) >= 3 && args[1] == "unset":
		delete(cfg, args[2])
		if err := env.SaveConfig(id, cfg); err != nil {
			return err
		}
		ui.Ok(out, "%s.%s 已删除", p.Manifest.Name, args[2])
		return nil
	default:
		masked := map[string]string{}
		for k, v := range cfg {
			if isSecretKey(p.Manifest, k) && v != "" {
				v = "********"
			}
			masked[k] = v
		}
		return printJSON(out, masked)
	}
}

func isSecretKey(m plugin.Manifest, key string) bool {
	for _, field := range m.Contributes.ConfigFields {
		if field.Key == key && field.Secret {
			return true
		}
	}
	for _, s := range m.Permissions.Secrets {
		if s == key {
			return true
		}
	}
	return false
}

func findings(env plugin.Env, args []string, out io.Writer) error {
	store, err := openStore(env)
	if err != nil {
		return err
	}
	defer store.Close()
	rows, err := store.Findings("", "", "")
	if err != nil {
		return err
	}
	if hasFlag(args, "--json") {
		return printJSON(out, rows)
	}
	for _, f := range rows {
		loc := f.File
		if f.Line > 0 {
			loc = fmt.Sprintf("%s:%d", f.File, f.Line)
		}
		fmt.Fprintf(out, "#%-4d %-7s %-8s %-24s %s %s\n", f.ID, f.Severity, f.Status, loc, f.Title, ui.Dim(f.Job))
	}
	return nil
}

func notifications(env plugin.Env, args []string, out io.Writer) error {
	store, err := openStore(env)
	if err != nil {
		return err
	}
	defer store.Close()
	rows, err := store.Notifications(50)
	if err != nil {
		return err
	}
	if hasFlag(args, "--json") {
		return printJSON(out, rows)
	}
	for _, n := range rows {
		fmt.Fprintf(out, "%s [%s] %s %s\n", n.Created, n.Type, n.Title, ui.Dim(n.Source))
	}
	return nil
}

func audit(env plugin.Env, args []string, out io.Writer) error {
	pluginID := ""
	if len(args) > 0 && !strings.HasPrefix(args[0], "--") {
		store, err := openStore(env)
		if err != nil {
			return err
		}
		p, err := store.Get(args[0])
		store.Close()
		if err != nil {
			return err
		}
		pluginID = p.Manifest.ID
	}
	entries, err := env.AuditTail(pluginID, 100)
	if err != nil {
		return err
	}
	if hasFlag(args, "--json") {
		return printJSON(out, entries)
	}
	for _, e := range entries {
		mark := ""
		if e.Decision == "denied" {
			mark = ui.Bold(" DENIED")
		}
		fmt.Fprintf(out, "%s %-20s %-22s %-30s%s %s\n", e.Time, e.Plugin, e.Action, e.Target, mark, ui.Dim(e.Result))
	}
	return nil
}

func status(env plugin.Env, args []string, out io.Writer) error {
	st := plugin.DaemonStatus(env)
	store, err := openStore(env)
	if err != nil {
		return err
	}
	defer store.Close()
	running, _ := store.Sessions("", "running")
	if hasFlag(args, "--json") {
		return printJSON(out, map[string]any{"daemon": st, "sessions": running})
	}
	if st == nil {
		fmt.Fprintf(out, "plugind: %s(启动: roami plugin daemon)\n", ui.Dim("not running"))
	} else {
		fmt.Fprintf(out, "plugind: running pid=%.0f enabled=%.0f/%.0f watching=%.0f sessions\n",
			asF(st["pid"]), asF(st["enabled"]), asF(st["plugins"]), asF(st["watchedSessions"]))
	}
	for _, r := range running {
		fmt.Fprintf(out, "  · %s %s job=%s\n", r.Session, ui.Dim(r.Plugin), r.Job)
	}
	return nil
}

// install 安装外部插件:目录或 .tgz/.tar.gz 包(node/exec 运行时)。
// 文件落 $TTMUX_HOME/plugins/installed/<id>/<version>/,安装后默认不启用。
func install(env plugin.Env, args []string, out io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: roami plugin install <目录|插件包.tgz>")
	}
	src, err := filepath.Abs(args[0])
	if err != nil {
		return err
	}
	root := src
	st, err := os.Stat(src)
	if err != nil {
		return err
	}
	if !st.IsDir() {
		if !strings.HasSuffix(src, ".tgz") && !strings.HasSuffix(src, ".tar.gz") {
			return fmt.Errorf("install source must be a directory or .tgz/.tar.gz, got %s", src)
		}
		tmp, err := os.MkdirTemp("", "roam-plugin-install-")
		if err != nil {
			return err
		}
		defer os.RemoveAll(tmp)
		if err := plugin.ExtractTgz(src, tmp); err != nil {
			return err
		}
		root = tmp
		// 包顶层是单个目录(常见打包形态)时下钻一层找 manifest
		if _, err := os.Stat(filepath.Join(root, "roam-plugin.json")); err != nil {
			entries, _ := os.ReadDir(root)
			if len(entries) == 1 && entries[0].IsDir() {
				root = filepath.Join(root, entries[0].Name())
			}
		}
	}
	m, err := plugin.ParseManifestFile(root)
	if err != nil {
		return err
	}
	if m.Runtime.Kind == "builtin" {
		return fmt.Errorf("runtime.kind builtin is reserved for built-in plugins")
	}
	store, err := openStore(env)
	if err != nil {
		return err
	}
	defer store.Close()
	if existing, err := store.Get(m.ID); err == nil && existing.Manifest.Runtime.Kind == "builtin" {
		return fmt.Errorf("plugin id %s conflicts with a built-in plugin", m.ID)
	}
	dest := filepath.Join(env.InstalledRoot(), m.ID, m.Version)
	if err := os.RemoveAll(dest); err != nil {
		return err
	}
	if err := plugin.CopyDir(root, dest); err != nil {
		return err
	}
	if err := store.InstallExternal(m, dest); err != nil {
		return err
	}
	env.Audit(plugin.AuditEntry{Plugin: m.ID, Version: m.Version, Actor: actor(), Action: "plugin.install", Target: src, Decision: "allowed"})
	ui.Ok(out, "已安装 %s v%s(%s 运行时,默认未启用)", ui.Bold(m.ID), m.Version, m.Runtime.Kind)
	if b, err := json.MarshalIndent(m.Permissions, "", "  "); err == nil {
		fmt.Fprintf(out, "权限声明(启用即授予,见安全设计):\n%s\n", string(b))
	}
	ui.Info(out, "启用: roami plugin enable %s", m.Name)
	return nil
}

// uninstall 移除外部插件:先停掉插件还在跑的会话,再删注册行/孤儿数据行/
// 安装文件。默认保留 storage/config 以便重装复用;加 --purge 则连同清除。
func uninstall(env plugin.Env, args []string, out io.Writer) error {
	purge := hasFlag(args, "--purge")
	id := firstNonFlag(args)
	if id == "" {
		return fmt.Errorf("usage: roami plugin uninstall <id> [--purge]")
	}
	store, err := openStore(env)
	if err != nil {
		return err
	}
	defer store.Close()
	p, err := store.Get(id)
	if err != nil {
		return err
	}
	if p.Manifest.Runtime.Kind == "builtin" {
		// 内置插件编译在二进制里,删不掉文件:改为软删(tombstone)——从列表隐藏、
		// SyncBuiltins 不会复活,可经「安装」入口(roami plugin restore)恢复。
		stopPluginSessions(env, store, p.Manifest.ID)
		if err := store.SoftRemove(p.Manifest.ID); err != nil {
			return err
		}
		env.Audit(plugin.AuditEntry{Plugin: p.Manifest.ID, Version: p.Manifest.Version, Actor: actor(), Action: "plugin.uninstall", Decision: "allowed"})
		if purge {
			_ = os.RemoveAll(env.StorageDir(p.Manifest.ID))
			ui.Ok(out, "已卸载内置插件 %s(含配置与数据,--purge;可在「安装」入口恢复)", ui.Bold(p.Manifest.ID))
			return nil
		}
		ui.Ok(out, "已卸载内置插件 %s(配置保留;可在「安装」入口恢复)", ui.Bold(p.Manifest.ID))
		return nil
	}
	// 先停掉插件还活着的会话(spawn 的评审会话 + im-bridge 常驻监听会话),
	// 免得进程继续引用即将被删的插件文件。
	stopPluginSessions(env, store, p.Manifest.ID)
	if err := store.Remove(p.Manifest.ID); err != nil {
		return err
	}
	// 只清理受管安装目录内的文件,别的路径一律不动
	if p.InstallPath != "" && strings.HasPrefix(p.InstallPath, env.InstalledRoot()+string(os.PathSeparator)) {
		_ = os.RemoveAll(filepath.Dir(p.InstallPath)) // <id>/ 整目录(含各版本)
	}
	env.Audit(plugin.AuditEntry{Plugin: p.Manifest.ID, Version: p.Manifest.Version, Actor: actor(), Action: "plugin.uninstall", Decision: "allowed"})
	if purge {
		_ = os.RemoveAll(env.StorageDir(p.Manifest.ID))
		ui.Ok(out, "已卸载 %s(含配置与数据,--purge)", ui.Bold(p.Manifest.ID))
		return nil
	}
	ui.Ok(out, "已卸载 %s(配置与数据保留在 storage,可重装复用;彻底清除加 --purge)", ui.Bold(p.Manifest.ID))
	return nil
}

// restore 恢复被卸载的内置插件:清掉软删标记并重新启用。manifest 已由 openStore
// 的 SyncBuiltins 刷新。外部插件不适用(请重新安装插件包)。
func restore(env plugin.Env, args []string, out io.Writer) error {
	id := firstNonFlag(args)
	if id == "" {
		return fmt.Errorf("usage: roami plugin restore <id>")
	}
	store, err := openStore(env)
	if err != nil {
		return err
	}
	defer store.Close()
	p, err := store.Get(id)
	if err != nil {
		return err
	}
	if p.Manifest.Runtime.Kind != "builtin" {
		return fmt.Errorf("只有内置插件支持恢复;外部插件请重新安装插件包")
	}
	if err := store.Restore(p.Manifest.ID); err != nil {
		return err
	}
	env.Audit(plugin.AuditEntry{Plugin: p.Manifest.ID, Version: p.Manifest.Version, Actor: actor(), Action: "plugin.restore", Decision: "allowed"})
	ui.Ok(out, "已恢复内置插件 %s", ui.Bold(p.Manifest.ID))
	return nil
}

// stopPluginSessions kills any live tmux sessions the plugin owns. 用 =name
// 精确匹配,避免前缀误伤(见 tmux -t 前缀匹配坑)。
func stopPluginSessions(env plugin.Env, store *plugin.Store, id string) {
	rows, _ := store.Sessions(id, "")
	for _, r := range rows {
		if env.RT.HasSession(r.Session) {
			_ = env.RT.Tmux("kill-session", "-t", "="+r.Session)
		}
	}
	// im-bridge 的入站监听会话由 plugind 直接拉起,不登记在 plugin_sessions,单独收
	if id == "roam.im-bridge" && env.RT.HasSession(plugin.IMListenerSession) {
		_ = env.RT.Tmux("kill-session", "-t", "="+plugin.IMListenerSession)
	}
}

// firstNonFlag returns the first positional (non---flag) arg, or "".
func firstNonFlag(args []string) string {
	for _, a := range args {
		if !strings.HasPrefix(a, "--") {
			return a
		}
	}
	return ""
}

// track 把一个已存在的会话登记给插件跟踪:plugind 在其退出时向该插件派发
// session:agent.exited 事件(如「结束后自动互审」给会话打 review:auto 标签)。
func track(env plugin.Env, args []string, out io.Writer) error {
	if len(args) < 1 || strings.HasPrefix(args[0], "--") {
		return fmt.Errorf("usage: roami plugin track <session> [--plugin <id>] [--job <id>] [--label k=v ...]")
	}
	session := args[0]
	pluginName := "review-mesh"
	job := ""
	labels := map[string]string{}
	for i := 1; i < len(args); i++ {
		switch args[i] {
		case "--plugin":
			if i+1 < len(args) {
				pluginName = args[i+1]
				i++
			}
		case "--job":
			if i+1 < len(args) {
				job = args[i+1]
				i++
			}
		case "--label":
			if i+1 < len(args) {
				if k, v, ok := strings.Cut(args[i+1], "="); ok {
					labels[k] = v
				}
				i++
			}
		}
	}
	store, err := openStore(env)
	if err != nil {
		return err
	}
	defer store.Close()
	p, err := store.Get(pluginName)
	if err != nil {
		return err
	}
	if !p.Enabled {
		return fmt.Errorf("plugin %s is disabled", p.Manifest.ID)
	}
	if err := store.AddSession(plugin.SessionRow{Session: session, Plugin: p.Manifest.ID, Job: job, Labels: labels}); err != nil {
		return err
	}
	// 事件驱动依赖 plugind;顺手确保它在跑(失败不阻断登记,提示即可)
	if err := plugin.EnsureDaemon(env); err != nil {
		ui.Warn(out, "plugind 未能启动(%v)——会话退出事件不会被侦测,可稍后手动: roami plugin daemon", err)
	}
	ui.Ok(out, "会话 %s 已登记给 %s 跟踪", ui.Bold(session), p.Manifest.ID)

	// 自动互审:再拉一个可见的监控会话陪跑(空闲即互审、意见回灌;
	// 会话结束或监控命令返回后该会话自行消亡)
	if labels["review:auto"] == "true" && p.Manifest.Name == "review-mesh" && labels["workdir"] != "" {
		self, err := os.Executable()
		if err != nil {
			return err
		}
		watchSess := session + "-review" // 命名约定:<做事的会话>-review
		if !env.RT.HasSession(watchSess) {
			cmd := fmt.Sprintf("%s plugin run review-mesh.watch --session %s --workdir %s",
				shellQuote(self), shellQuote(session), shellQuote(labels["workdir"]))
			if err := env.RT.Tmux("new-session", "-d", "-s", watchSess, cmd); err != nil {
				ui.Warn(out, "监控会话拉起失败: %v", err)
			} else {
				// meta 记 parent=被陪跑会话:Web 父子树把陪跑会话归到同一组,
				// 而不是游离的顶层会话(被陪跑会话本身是 fork 出来的时尤其明显)
				if err := sessmeta.New(env.RT.HomeDir).Put(sessmeta.Row{
					Session: watchSess, Parent: session, CreatedBy: "review-watch", InitialCwd: labels["workdir"],
				}); err != nil {
					ui.Warn(out, "监控会话 parent 元数据写入失败: %v", err)
				}
				ui.Ok(out, "监控会话 %s 已陪跑(围观: roami session a %s)", ui.Bold(watchSess), watchSess)
			}
		}
	}
	return nil
}

func shellQuote(s string) string {
	return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'"
}

func help(out io.Writer) {
	fmt.Fprint(out, `用法: roami plugin <子命令>

  ls [--json] [--removed]             列出插件与其命令(--removed 列出已卸载待恢复的内置插件)
  install <目录|包.tgz>                安装外部插件(node/exec 运行时,默认未启用)
  uninstall <id> [--purge]            卸载插件(内置=软删可恢复;--purge 连配置数据一并清除)
  restore <id>                        恢复被卸载的内置插件
  info <id> [--json]                  插件详情(manifest、权限、状态)
  enable|disable <id>                 启用 / 禁用插件
  run <插件>.<命令> [--key value ...]  调用插件命令(如 review-mesh.review)
  config <id> [set k v | unset k]     查看 / 修改插件配置
  findings [--json]                   查看互审 finding
  notifications [--json]              查看通知流
  audit [<id>] [--json]               查看审计日志
  status                              守护进程与会话状态
  track <会话> [--label k=v ...]       登记会话给插件跟踪(退出时派发事件)
  daemon [--foreground]               启动 plugind(异步事件收尾需要)

示例:
  roami plugin run review-mesh.review              # 互审当前工作区变更
  roami plugin config im-bridge set app_id <cli_xxx>
  roami plugin run im-bridge.test                  # 发送 IM 测试卡片
`)
}

// ── helpers ──

func actor() string {
	if u, err := user.Current(); err == nil {
		return "cli:" + u.Username
	}
	return "cli:user"
}

// parseFlags turns [--k v --flag] into {k:v, flag:"true"}.
func parseFlags(args []string) map[string]string {
	out := map[string]string{}
	for i := 0; i < len(args); i++ {
		if !strings.HasPrefix(args[i], "--") {
			continue
		}
		key := strings.TrimPrefix(args[i], "--")
		if i+1 < len(args) && !strings.HasPrefix(args[i+1], "--") {
			out[key] = args[i+1]
			i++
		} else {
			out[key] = "true"
		}
	}
	return out
}

func asF(v any) float64 {
	f, _ := v.(float64) // JSON 数字解码为 float64
	return f
}

func hasFlag(args []string, want string) bool {
	for _, a := range args {
		if a == want {
			return true
		}
	}
	return false
}

func printJSON(out io.Writer, v any) error {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	fmt.Fprintln(out, string(b))
	return nil
}

func printRaw(out io.Writer, raw json.RawMessage) error {
	var v any
	if err := json.Unmarshal(raw, &v); err != nil {
		fmt.Fprintln(out, string(raw))
		return nil
	}
	return printJSON(out, v)
}
