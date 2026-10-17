package main

import (
	"fmt"
	"github.com/ybz21/Roami/backend/browser/automation"
	"github.com/ybz21/Roami/internal/cli"
	"github.com/ybz21/Roami/internal/plugin"
	"github.com/ybz21/Roami/internal/tmuxruntime"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
)

// pluginInfo 是 `ttmux plugin ls --json` 里我们用得上的那几项。
type pluginInfo struct {
	ID       string // roam.im-bridge
	Name     string // im-bridge
	Enabled  bool
	Commands []string // im-bridge.send …
	Summary  string
}

// resolveGroup 把用户敲的词认成插件：全名 > 短名 > 唯一前缀。
// 认不出返回空（调用方据此转发给 ttmux）；前缀撞了要报错——
// 猜一个跑出去比说不认识危险得多。
func resolveGroup(plugins []pluginInfo, word string) (*pluginInfo, error) {
	var hits []int
	for i, p := range plugins {
		if p.ID == word || p.Name == word {
			return &plugins[i], nil
		}
		if strings.HasPrefix(p.Name, word) {
			hits = append(hits, i)
		}
	}
	switch len(hits) {
	case 0:
		return nil, nil
	case 1:
		return &plugins[hits[0]], nil
	default:
		names := make([]string, 0, len(hits))
		for _, i := range hits {
			names = append(names, plugins[i].Name)
		}
		sort.Strings(names)
		return nil, fmt.Errorf("%q 对得上好几个插件：%s——写全一点", word, strings.Join(names, " / "))
	}
}

// pluginRunArgs 拼出转发给 ttmux 的参数。命令用 id 限定形式（roam.cron:list），
// 归属由注册表按全 id 精确判定，不会落到短名撞名的另一个插件上。
func pluginRunArgs(p pluginInfo, cmd string, rest []string) []string {
	return append([]string{"plugin", "run", p.ID + ":" + cmd}, rest...)
}

// shortCmd 把 contributes 里的 "cron.list" 剥成 "list"。
func shortCmd(id string) string {
	if _, after, ok := strings.Cut(id, "."); ok {
		return after
	}
	return id
}

func loadPlugins(_ string) []pluginInfo {
	list, _ := discoverPlugins()
	return list
}

func discoverPlugins() ([]pluginInfo, error) {
	store, err := plugin.Open(plugin.NewEnv(runtime.New()))
	if err != nil {
		return nil, err
	}
	defer store.Close()
	if err := plugin.SyncBuiltins(store); err != nil {
		return nil, err
	}
	entries, err := store.List()
	if err != nil {
		return nil, err
	}
	list := make([]pluginInfo, 0, len(entries))
	for _, r := range entries {
		p := pluginInfo{ID: r.Manifest.ID, Name: r.Manifest.Name, Enabled: r.Enabled, Summary: r.Manifest.Description.Get("zh-CN")}
		for _, c := range r.Manifest.Contributes.Commands {
			p.Commands = append(p.Commands, shortCmd(c.ID))
		}
		list = append(list, p)
	}
	return list, nil
}

func runSession(args []string) int { return runSessionEngine(args) }

func runSessionEngine(args []string) int {
	needsStorage := len(args) == 0 || (args[0] != "help" && args[0] != "--help" && args[0] != "-h" && args[0] != "--version" && args[0] != "-v")
	if needsStorage {
		release, err := instanceLease()
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		defer release()
	}

	if err := app.New().Run(args); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}

// runCLI 处理子命令。返回 false 表示「这不是子命令」，main 照旧启动服务。
func runCLI(args []string, _ string) (handled bool, code int) {
	base := filepath.Base(os.Args[0])
	if base == "ttmux" || (strings.HasPrefix(base, "ttmux-") && base != "ttmux-web") {
		return true, runSession(args)
	}
	if base == "chrome" {
		return true, runChrome(args)
	}
	if len(args) == 0 {
		return false, 0
	}
	word, rest := args[0], args[1:]
	switch word {
	case "help", "commands", "-h", "--help":
		if len(rest) > 0 {
			switch rest[0] {
			case "session", "ttmux":
				return true, runSession([]string{"help"})
			case "chrome":
				return true, runChrome([]string{"help"})
			case "project", "auth":
				return true, runAPICommand(rest[0], []string{"help"})
			case "db":
				return true, runDatabase([]string{"help"})
			case "server":
				fmt.Println("roami server [-config PATH] [-addr HOST:PORT] [-tls] [-tls-cert PATH] [-tls-key PATH] [-web DIR]")
				return true, 0
			}
		}
		printHelp(nil)
		return true, 0
	case "version", "--version", "-v":
		fmt.Println("roami " + displayVersion())
		return true, 0
	case "session", "ttmux":
		return true, runSession(rest)
	case "db":
		return true, runDatabase(rest)
	case "plugin", "__autoconfirm", "_plugin-host":
		return true, runSession(args)
	case "chrome":
		return true, runChrome(rest)
	case "completion":
		fmt.Print(completionScript)
		return true, 0
	case "project", "auth":
		return true, runAPICommand(word, rest)
	}
	if strings.HasPrefix(word, "-") {
		return false, 0
	}
	if legacySessionCommand(word) {
		return true, runSession(args)
	}
	plugins, err := discoverPlugins()
	if err != nil {
		fmt.Fprintln(os.Stderr, "插件发现失败:", err)
		return true, 1
	}
	p, err := resolveGroup(plugins, word)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return true, 2
	}
	if p == nil {
		fmt.Fprintf(os.Stderr, "未知命令 %q；使用 roami help 查看命令\n", word)
		return true, 2
	}
	if len(rest) == 0 || rest[0] == "help" || rest[0] == "--help" {
		printGroup(*p)
		return true, 0
	}
	if !p.Enabled {
		fmt.Fprintf(os.Stderr, "插件 %s 已停用；使用 roami plugin enable %s\n", p.Name, p.ID)
		return true, 2
	}
	return true, runSession(pluginRunArgs(*p, rest[0], rest[1:]))
}

func legacySessionCommand(word string) bool {
	switch word {
	case "ls", "new", "fork", "children", "parent", "a", "attach", "d", "detach", "kill", "killall", "rename", "resolve", "send", "source", "nw", "lw", "kw", "sp", "split", "kp", "capture", "status", "env", "info", "swarm":
		return true
	}
	return false
}

func runChrome(args []string) int {
	if err := automation.Run(args); err != nil {
		fmt.Fprintln(os.Stderr, err)
		if e, ok := err.(*exec.ExitError); ok {
			return e.ExitCode()
		}
		return 1
	}
	return 0
}

const completionScript = `_roami_complete() {
 local cur="${COMP_WORDS[COMP_CWORD]}"
 local words="session chrome project db server auth plugin help version completion"
 case "${COMP_WORDS[1]}" in
 session) words="ls new attach detach kill rename send capture fork children parent swarm env info" ;;
 chrome) words="tabs goto click fill text eval screenshot record setup help" ;;
 project) words="ls show create prefs activity remove" ;;
 db) words="status migrate backup" ;;
 auth) words="login logout status" ;;
 esac
 COMPREPLY=($(compgen -W "$words" -- "$cur"))
}
complete -F _roami_complete roami
`

func forward(bin string, args []string) int {
	cmd := exec.Command(bin, args...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		var ee *exec.ExitError
		if ok := asExitError(err, &ee); ok {
			return ee.ExitCode()
		}
		fmt.Fprintf(os.Stderr, "调用 %s 失败: %v\n", bin, err)
		return 1
	}
	return 0
}

func printHelp(_ []pluginInfo) {
	fmt.Printf("roami %s — 统一命令入口\n\n", displayVersion())
	fmt.Println("  session <命令>     会话、窗格、蜂群与环境")
	fmt.Println("  chrome <命令>      浏览器自动化")
	fmt.Println("  project <命令>     ls / show / create / prefs / activity / remove")
	fmt.Println("  auth <命令>        login / logout / status")
	fmt.Println("  db <命令>          status / migrate / backup")
	fmt.Println("  plugin <命令>      插件管理；也可 roami <插件名> <命令>")
	fmt.Println("  server [flags]     启动 Web 服务（无参和旧 flags 继续兼容）")
	fmt.Println("  help / version / completion")
}

func printGroup(p pluginInfo) {
	fmt.Printf("  %s — %s\n\n", p.Name, firstLine(p.Summary))
	for _, c := range p.Commands {
		fmt.Printf("    roami %s %s\n", p.Name, c)
	}
}

// displayVersion 保证只有一个 v：注入的 tag 本身就带（v0.1.0-rc.2-…），
// 开发构建是裸的 "dev"。
func displayVersion() string {
	if strings.HasPrefix(version, "v") {
		return version
	}
	return "v" + version
}

func firstLine(s string) string {
	if i := strings.IndexAny(s, "\n;"); i > 0 {
		return s[:i]
	}
	return s
}
