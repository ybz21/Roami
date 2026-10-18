package spawn

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/ybz21/Roami/internal/agent"
	"github.com/ybz21/Roami/internal/sessionstore"
	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// spawnOne creates a single task session (cmd or agent), mirroring _spawn_one.
// 返回 (是否新建, 会话名(= 会话 id))：调用方要拿会话名去登记台账（蜂群成员表）。
func spawnOne(rt runtime.Runtime, group, name, taskType, payload string, ac AgentConfig, w io.Writer) (bool, string, error) {
	if err := rt.EnsureDirs(); err != nil {
		return false, "", err
	}
	// 任务的语义名 `<组>-<成员>` 现在是**展示名**：会话本身叫 id（改名/重名都不怕，
	// logs/meta/台账全按 id 存）。语义名写进 @roam_name + meta 的 label.txt，
	// 于是 `roami session send <组>-<成员>` 这类老用法照旧能命中（Resolve 反查展示名）。
	label := group + "-" + name
	if target := rt.Resolve(label); rt.HasSession(target) {
		ui.Warn(w, "会话 %s 已存在，跳过", ui.Bold(label))
		return false, target, nil
	}
	width := "200"
	if taskType == "agent" {
		width = "220"
	}
	if taskType == "agent" {
		prepared, prepareError := ac.PrepareInteractive(rt)
		if prepareError != nil {
			ui.Warn(w, "Codex lifecycle callbacks unavailable: %s", prepareError)
		}
		ac = prepared
	}
	sess, err := rt.CreateSession(runtime.CreateOpts{Label: label, Width: width, Height: "50"})
	if err != nil {
		return false, "", err
	}
	started := false
	defer func() {
		if !started {
			_ = rt.Tmux("kill-session", "-t", "="+sess)
			rt.CleanTaskMeta(sess)
		}
	}()
	rt.InjectEnv(sess)
	_ = rt.Tmux("pipe-pane", "-t", "="+sess, "-o", "cat >> '"+rt.LogFile(sess)+"'")
	_ = os.WriteFile(rt.LogFile(sess), nil, 0o644)
	RecordAgentSession(rt, sess, ac)
	if err := rt.WriteTaskMeta(sess, taskType, payload, ac.Workdir, label); err != nil {
		return false, sess, err
	}

	runCmd := payload
	if taskType == "agent" {
		promptFile := filepath.Join(rt.TaskMetaDir(sess), "prompt.txt")
		if err := os.WriteFile(promptFile, []byte(payload), 0600); err != nil {
			return false, sess, err
		}
		runCmd = ac.CommandFromPromptFile(promptFile)
		if ac.Interactive {
			runCmd = ac.InteractiveFromPromptFile(promptFile)
		}
	}
	if err := rt.SendShellCommand("="+sess, runCmd); err != nil {
		return false, sess, err
	}
	if taskType == "agent" && ac.Interactive && ac.Kind == "claude" {
		LaunchAutoconfirm(rt, sess)
	}
	if err := rt.GroupAddSession(group, sess); err != nil {
		return false, sess, err
	}
	started = true
	return true, sess, nil
}

// One launches a single task/agent session (exported for the swarm command
// layer, which composes spawn with the swarm data core). Returns true when a
// session was created.
func One(rt runtime.Runtime, group, name, taskType, payload string, ac AgentConfig, w io.Writer) (bool, string, error) {
	return spawnOne(rt, group, name, taskType, payload, ac, w)
}

// Spawn handles `spawn <group> <name> <cmd> ...` (command tasks), mirroring _do_spawn.
func Spawn(rt runtime.Runtime, args []string, w io.Writer) error {
	if err := rt.EnsureDirs(); err != nil {
		return err
	}
	if len(args) < 3 {
		ui.Err(w, "用法: roami session spawn <组名> <任务名> <命令> [<任务名> <命令> ...]")
		return fmt.Errorf("usage")
	}
	group := args[0]
	rest := args[1:]
	if rt.GroupExists(group) {
		ui.Warn(w, "任务组 %s 已存在，追加任务", ui.Bold(group))
	}
	wd, _ := os.Getwd()
	ac := DefaultAgentConfig(wd)
	count := 0
	i := 0
	for i+1 < len(rest) {
		name, cmd := rest[i], rest[i+1]
		i += 2
		ok, _, err := spawnOne(rt, group, name, "cmd", cmd, ac, w)
		if err != nil {
			return err
		}
		if ok {
			count++
			ui.Ok(w, "启动 %s: %s", ui.Bold(group+"-"+name), ui.Dim(cmd))
		}
	}
	if i < len(rest) {
		ui.Warn(w, "忽略落单参数: %s %s", rest[i], ui.Dim("(spawn 需要成对的 name+cmd)"))
	}
	fmt.Fprintln(w)
	ui.Info(w, "任务组 %s 已启动 %d 个任务", ui.Bold(group), count)
	return nil
}

// SpawnAgents handles `spawn --agent <group> <name> <task> ... [opts]`, mirroring _agent_spawn.
func SpawnAgents(rt runtime.Runtime, args []string, w io.Writer) error {
	if err := rt.EnsureDirs(); err != nil {
		return err
	}
	if len(args) < 1 {
		ui.Err(w, "用法: roami session spawn --agent <组名> <名称> <任务> [...] [选项]")
		return fmt.Errorf("usage")
	}
	group := args[0]
	rest := args[1:]
	wd, _ := os.Getwd()
	ac := DefaultAgentConfig(wd)
	var pairs []string
	for i := 0; i < len(rest); i++ {
		switch rest[i] {
		case "--dir":
			if i+1 < len(rest) {
				ac.Workdir = rest[i+1]
				i++
			}
		case "--model":
			if i+1 < len(rest) {
				ac.Model = rest[i+1]
				i++
			}
		case "--perm":
			if i+1 < len(rest) {
				ac.Permission = rest[i+1]
				i++
			}
		case "--max-turns":
			if i+1 < len(rest) {
				ac.MaxTurns = rest[i+1]
				i++
			}
		default:
			pairs = append(pairs, rest[i])
		}
	}
	if rt.GroupExists(group) {
		ui.Warn(w, "Agent 组 %s 已存在", ui.Bold(group))
		return fmt.Errorf("group exists")
	}
	if len(pairs) < 2 {
		ui.Err(w, "用法: roami session spawn --agent <组名> <名称> <任务> [...] [选项]")
		return fmt.Errorf("usage")
	}
	count := 0
	for i := 0; i+1 < len(pairs); i += 2 {
		name, task := pairs[i], pairs[i+1]
		ok, _, err := spawnOne(rt, group, name, "agent", task, ac, w)
		if err != nil {
			return err
		}
		if ok {
			count++
			suffix := ""
			if len(task) > 60 {
				suffix = "..."
			}
			ui.Ok(w, "Agent %s: %s", ui.Bold(name), ui.Dim(truncate(task, 60)+suffix))
		}
	}
	fmt.Fprintln(w)
	ui.Info(w, "Agent 组 %s 已启动 %d 个 Claude 实例", ui.Bold(group), count)
	ui.Info(w, "工作目录: %s", ui.Dim(ac.Workdir))
	return nil
}

// SpawnFile reads "<name> <payload>" lines from a file and spawns them
// (mirrors _do_spawn_file / _agent_spawn_file). agent toggles claude/codex mode.
func SpawnFile(rt runtime.Runtime, group, file string, extra []string, agent bool, w io.Writer) error {
	b, err := os.ReadFile(file)
	if err != nil {
		ui.Err(w, "文件不存在: %s", file)
		return err
	}
	args := []string{group}
	args = append(args, extra...)
	for _, line := range strings.Split(string(b), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		name, payload := cut(line)
		if name == "" {
			continue
		}
		args = append(args, name, payload)
	}
	if agent {
		return SpawnAgents(rt, args, w)
	}
	return Spawn(rt, args, w)
}

func cut(line string) (string, string) {
	i := strings.IndexAny(line, " \t")
	if i < 0 {
		return line, ""
	}
	return line[:i], strings.TrimSpace(line[i+1:])
}

// Wait blocks until a group's sessions finish or time out, mirroring _do_wait_group.
func Wait(rt runtime.Runtime, args []string, w io.Writer) error {
	timeout := 300
	group := ""
	for i := 0; i < len(args); i++ {
		if args[i] == "--timeout" && i+1 < len(args) {
			if n, err := strconv.Atoi(args[i+1]); err == nil {
				timeout = n
			}
			i++
		} else {
			group = args[i]
		}
	}
	if group == "" {
		ui.Err(w, "用法: roami session wait <组名> [--timeout N]")
		return fmt.Errorf("usage")
	}
	if !rt.GroupExists(group) {
		ui.Err(w, "任务组不存在: %s", group)
		return fmt.Errorf("group not found")
	}
	ui.Info(w, "等待任务组 %s 完成... %s", ui.Bold(group), ui.Dim(fmt.Sprintf("(超时 %ds)", timeout)))
	sessions, _ := rt.GroupSessions(group)
	allDone := true
	for _, sess := range sessions {
		sess = rt.ResolveAlive(sess) // 台账存 id；迁移前的老台账存名字，兜一下
		if !rt.WaitSession(sess, timeout) {
			allDone = false
			ui.Warn(w, "等待超时 (%ds): %s", timeout, rt.TaskLabel(sess))
		}
	}
	if allDone {
		ui.Ok(w, "任务组 %s 全部完成", ui.Bold(group))
	} else {
		ui.Warn(w, "任务组 %s 部分超时", ui.Bold(group))
	}
	return nil
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

// RecordAgentSession 把这次启动的归属目录、仓库根与 agent 对话 id 落进台账。
// 都是「现在不记，以后就永远算不出来」的东西：worktree 会被删、
// transcript 会被同目录的别的会话盖过去。
func RecordAgentSession(rt runtime.Runtime, sess string, ac AgentConfig) {
	if sess == "" {
		return
	}
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	_ = meta.SetHome(sess, ac.Workdir, repoRootOf(ac.Workdir))
	// 记下是哪种 agent：会话被机器重启带走后，恢复时靠它决定敲哪一型的命令。
	// 不记的话这一列永远是空，「按类型分派」就是一段永远走不到的代码。
	_ = meta.SetAgentKind(sess, ac.Kind)
	// 对话 id 由**这一型自己**说怎么来：能在启动时指定的（claude 的 --session-id）
	// 直接记我们指定的那个；Codex 等可信生命周期回报，不用旧 rollout 猜新会话。
	if a := agent.Get(ac.Kind); a != nil {
		if a.PinsConversationID() {
			_ = meta.SetAgentSession(sess, ac.SessionUUID)
		} else if got := observedConversationID(a, ac.Workdir); got != "" {
			_ = meta.SetAgentSession(sess, got)
		}
	}
}

// repoRootOf 求目录所属的 git 主仓库根（worktree 归位到主仓库）。
func repoRootOf(dir string) string {
	if dir == "" {
		return ""
	}
	out, err := exec.Command("git", "-C", dir, "rev-parse",
		"--path-format=absolute", "--git-common-dir").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSuffix(strings.TrimSuffix(strings.TrimSpace(string(out)), "/"), "/.git")
}

func observedConversationID(provider agent.Agent, directory string) string {
	if provider.Kind() == "codex" {
		return ""
	}
	return provider.DetectConversationID(directory)
}
