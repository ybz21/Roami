package swarm

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/ybz21/Roami/internal/agent"
	"github.com/ybz21/Roami/internal/cli/group"
	swarmcore "github.com/ybz21/Roami/internal/swarm"
	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// Run dispatches `swarm <subcommand>`. Data-plane mutations are native; plaza,
// board, and listener are still routed to the shell CLI.
func Run(rt runtime.Runtime, args []string, w io.Writer) error {
	subcmd := "ls"
	if len(args) > 0 {
		subcmd = args[0]
		args = args[1:]
	}
	st := swarmcore.NewStore(opts(rt))
	switch subcmd {
	case "new", "create":
		return cmdNew(rt, st, args, w)
	case "add":
		return cmdAdd(rt, st, args, w)
	case "done":
		return cmdDone(rt, st, args, w)
	case "activate":
		return cmdActivate(rt, st, args, w)
	case "adopt":
		return cmdAdopt(rt, st, args, w)
	case "ls", "list":
		return cmdList(rt, st, args, w)
	case "archive":
		return cmdArchive(rt, st, args, w)
	case "rm", "delete":
		return cmdRemove(rt, st, args, w)
	case "sql":
		return cmdSQL(st, args, w)
	case "collect":
		if len(args) < 1 {
			return fmt.Errorf("usage: roami session swarm collect <name> [--json]")
		}
		if !st.Exists(args[0]) {
			ui.Err(w, "蜂群不存在: %s", args[0])
			return fmt.Errorf("not found")
		}
		if len(args) > 1 && args[1] == "--json" {
			return group.CollectJSON(rt, args[0], w)
		}
		if !rt.GroupExists(args[0]) {
			ui.Info(w, "蜂群 %s 还没有成员", ui.Bold(args[0]))
			return nil
		}
		return group.CollectText(rt, args[0], w)
	case "status":
		if len(args) < 1 {
			return fmt.Errorf("usage: roami session swarm status <name> [--json]")
		}
		if len(args) > 1 && args[1] == "--json" {
			out, err := swarmcore.StatusJSON(args[0], opts(rt))
			if err != nil {
				return err
			}
			_, err = fmt.Fprintln(w, string(out))
			return err
		}
		return cmdStatusText(rt, st, args[0], w)
	case "say":
		return cmdSay(rt, st, args, w)
	case "feed":
		return cmdFeed(rt, st, args, w)
	case "watch":
		return cmdWatch(rt, st, args, w)
	case "listen":
		return cmdListen(rt, st, args, w)
	case "board":
		return cmdBoard(st, args, w)
	case "task":
		return cmdTask(st, args, w)
	case "migrate":
		n, err := st.Migrate(
			func(g string) []string { s, _ := rt.GroupSessions(g); return s },
			rt.TaskType, rt.TaskDesc,
		)
		if err != nil {
			return err
		}
		ui.Ok(w, "蜂群历史数据迁移完成 (%d 个)", n)
		return nil
	default:
		return fmt.Errorf("unknown subcommand: swarm %s", subcmd)
	}
}

func opts(rt runtime.Runtime) swarmcore.Options {
	return swarmcore.Options{HomeDir: rt.HomeDir, DataDir: rt.DataDir, TmuxBin: rt.TmuxBin, Now: rt.Now}
}

func cmdNew(rt runtime.Runtime, st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 1 {
		ui.Err(w, "用法: roami session swarm new <名> [--goal \"...\"]")
		return fmt.Errorf("usage")
	}
	name := args[0]
	if st.Exists(name) {
		ui.Warn(w, "蜂群 %s 已存在", ui.Bold(name))
		return fmt.Errorf("exists")
	}
	goal, noMaster, dir, leaderPrompt := "", false, "", ""
	for i := 1; i < len(args); i++ {
		switch args[i] {
		case "--goal":
			if i+1 < len(args) {
				goal = args[i+1]
				i++
			}
		case "--dir":
			if i+1 < len(args) {
				dir = args[i+1]
				i++
			}
		case "--leader-prompt":
			if i+1 < len(args) {
				leaderPrompt = args[i+1]
				i++
			}
		case "--no-master":
			noMaster = true
		}
	}
	// 指定了工作目录就先建好：Leader 会 cd 进去、上传的文档也落在这里
	if dir != "" {
		_ = os.MkdirAll(dir, 0o755)
	}
	// 绝对路径入库：Web 项目视图按 dir 归属蜂群(issue #125)，相对路径跨进程无意义
	dirAbs := absDir(dir)
	if dirAbs == "" && stdinIsTTY() {
		// 人(或终端里的 agent)直接 `swarm new` 没给 --dir：Leader 就地在当前目录
		// 起，那当前目录就是这个蜂群的工作目录，记下来 Web 才归得了项目。
		// 后端(web)调 CLI 时 stdin 是管道，不走这条——否则会把服务进程的 cwd
		// 当成蜂群目录，归到一个八竿子打不着的项目上。
		dirAbs, _ = os.Getwd()
	}
	id, err := st.NewSwarm(name, goal, dirAbs)
	if err != nil {
		return err
	}
	ui.Ok(w, "蜂群 %s 已创建 %s", ui.Bold(name), ui.Dim("("+id+")"))
	if !ui.AgentMode() { // decorative hints: humans only, keep agent stdout clean
		if goal != "" {
			fmt.Fprintf(w, "   %s目标: %s%s\n", ui.P().Dim, goal, ui.P().Reset)
		}
		fmt.Fprintf(w, "   %s加成员: roami session swarm add %s <名> --type agent \"<任务>\"%s\n", ui.P().Dim, name, ui.P().Reset)
	}
	if !noMaster {
		if hasClaude() {
			if !ui.AgentMode() {
				fmt.Fprintf(w, "   %s拉起 Leader cc-%s …%s\n", ui.P().Dim, name, ui.P().Reset)
			}
			_ = adopt(rt, st, name, "", dir, leaderPrompt, w)
		} else {
			ui.Info(w, "未检测到 claude，未拉起 Leader；稍后手动: %s", ui.Dim("roami session swarm adopt "+name))
		}
	}
	return nil
}

func cmdAdd(rt runtime.Runtime, st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 2 {
		ui.Err(w, "用法: roami session swarm add <群> <成员> [--type task|agent] <命令或任务>")
		return fmt.Errorf("usage")
	}
	swarm, member := args[0], args[1]
	rest := args[2:]
	if !st.Exists(swarm) {
		ui.Err(w, "蜂群不存在: %s  %s", swarm, ui.Dim("(先 roami session swarm new "+swarm+")"))
		return fmt.Errorf("not found")
	}
	wd, _ := os.Getwd()
	spec := swarmcore.MemberSpec{Name: member, Type: "agent", Kind: "claude", Workdir: wd}
	deps := ""
	var payload []string
	for i := 0; i < len(rest); i++ {
		switch rest[i] {
		case "--type":
			spec.Type, i = next(rest, i)
		case "--dir":
			spec.Workdir, i = next(rest, i)
		case "--model":
			spec.Model, i = next(rest, i)
		case "--perm":
			spec.Perm, i = next(rest, i)
		case "--depends-on":
			deps, i = next(rest, i)
		case "--kind":
			spec.Kind, i = next(rest, i)
		case "--role":
			spec.Role, i = next(rest, i)
		case "--subrole":
			spec.Subrole, i = next(rest, i)
		case "--duty":
			spec.Duty, i = next(rest, i)
		default:
			payload = append(payload, rest[i])
		}
	}
	spec.Task = strings.Join(payload, " ")
	if spec.Task == "" {
		ui.Err(w, "缺少%s内容: 命令(task) 或 任务描述(agent)", spec.Type)
		return fmt.Errorf("empty payload")
	}
	if spec.Type != "task" && spec.Type != "agent" {
		ui.Err(w, "--type 只能是 task 或 agent")
		return fmt.Errorf("bad type")
	}
	// 认哪些 kind 由注册表说了算，不写死在这里：
	// 新增一型只要实现 agent.Agent 并 Register，这里自动接受它。
	if spec.Type == "agent" && agent.Get(spec.Kind) == nil {
		ui.Err(w, "--kind 只能是 %s", strings.Join(agent.Kinds(), " 或 "))
		return fmt.Errorf("bad kind")
	}
	spec.Role = swarmcore.RoleNorm(spec.Role)
	if spec.Role == "" {
		if spec.Type == "agent" && !st.HasLeader(swarm) {
			spec.Role = "leader"
		} else {
			spec.Role = "member"
		}
	}
	// 软依赖：记录依赖关系（供拓扑连线 + 写进成员 prompt 协调），但**不挂起**——
	// 成员一建出来就立即起会话开工，缺上游产出时自己去广场等/问（见 worker.md.tmpl 的依赖段）。
	if deps != "" {
		if err := st.DepSet(swarm, member, deps); err != nil {
			return err
		}
	}
	ok, err := launchMember(rt, st, swarm, spec, w)
	if err != nil {
		return err
	}
	if ok {
		if err := st.AddMemberRow(swarm, spec); err != nil {
			return err
		}
		_ = st.MetaSet(swarm, "status", "running")
		ui.Ok(w, "成员 %s (%s/%s/%s): %s", ui.Bold(member), spec.Type, spec.Kind, spec.Role, ui.Dim(trunc(spec.Task, 60)))
	}
	return nil
}

func cmdDone(rt runtime.Runtime, st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 1 {
		ui.Err(w, "用法: roami session swarm done <群> [成员]")
		return fmt.Errorf("usage")
	}
	name := args[0]
	if !st.Exists(name) {
		ui.Err(w, "蜂群不存在: %s", name)
		return fmt.Errorf("not found")
	}
	if len(args) >= 2 && args[1] != "" {
		member := args[1]
		if err := st.MarkMemberDone(name, member); err != nil {
			return err
		}
		ui.Ok(w, "成员 %s 已标记完成 %s", ui.Bold(name+"-"+member), ui.Dim("(会话不动)"))
		_, _ = st.Activate(name, "", false, spawnCallback(rt, st, w))
		return nil
	}
	if err := st.MetaSet(name, "status", "done"); err != nil {
		return err
	}
	ui.Ok(w, "蜂群 %s 已标记完成", ui.Bold(name))
	return nil
}

func cmdActivate(rt runtime.Runtime, st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 1 {
		ui.Err(w, "用法: roami session swarm activate <群> [成员] [--force]")
		return fmt.Errorf("usage")
	}
	swarm := args[0]
	only, force := "", false
	for i := 1; i < len(args); i++ {
		switch args[i] {
		case "--force":
			force = true
		case "--quiet":
		default:
			only = args[i]
		}
	}
	if !st.Exists(swarm) {
		ui.Err(w, "蜂群不存在: %s", swarm)
		return fmt.Errorf("not found")
	}
	n, err := st.Activate(swarm, only, force, spawnCallback(rt, st, w))
	if err != nil {
		return err
	}
	if n > 0 {
		_ = st.MetaSet(swarm, "status", "running")
	} else if rest := len(st.PendingList(swarm)); rest > 0 {
		ui.Info(w, "无可解锁成员 %s", ui.Dim(fmt.Sprintf("(还有 %d 个在等依赖)", rest)))
	} else {
		ui.Info(w, "没有挂起的成员")
	}
	return nil
}

func cmdArchive(rt runtime.Runtime, st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: roami session swarm archive <name>")
	}
	name := args[0]
	if !st.Exists(name) {
		ui.Err(w, "蜂群不存在: %s", name)
		return fmt.Errorf("not found")
	}
	if rt.GroupExists(name) {
		_ = group.Kill(rt, name, w)
	}
	_ = st.MetaSet(name, "status", "archived")
	ui.Ok(w, "蜂群 %s 已归档 %s", ui.Bold(name), ui.Dim("(会话已清，元数据保留)"))
	return nil
}

func cmdRemove(rt runtime.Runtime, st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: roami session swarm rm <name> [--yes]")
	}
	name := ""
	yes := false
	for _, a := range args {
		switch a {
		case "--yes", "-y":
			yes = true
		default:
			if name == "" {
				name = a
			}
		}
	}
	if name == "" {
		return fmt.Errorf("usage: roami session swarm rm <name> [--yes]")
	}
	if !st.Exists(name) {
		ui.Err(w, "蜂群不存在: %s", name)
		return fmt.Errorf("not found")
	}
	// --yes (or agent mode) skips the /dev/tty confirm so agents/scripts can
	// delete non-interactively.
	if !yes && !ui.AgentMode() && !ui.Confirm("确定彻底删除蜂群 "+ui.Bold(name)+"(含会话与元数据)?") {
		ui.Info(w, "已取消")
		return nil
	}
	if rt.GroupExists(name) {
		_ = group.Kill(rt, name, io.Discard)
	}
	if err := st.Remove(name); err != nil {
		return err
	}
	ui.Ok(w, "蜂群 %s 已删除", ui.Bold(name))
	return nil
}

// absDir 把 --dir 规整成绝对路径（空值/"." 视为未指定，返回 ""）——落库的目录
// 要能被 Web 端跟项目目录直接比对，相对路径取决于 CLI 当时的 cwd，没法比。
func absDir(dir string) string {
	dir = strings.TrimSpace(dir)
	if dir == "" || dir == "." {
		return ""
	}
	abs, err := filepath.Abs(dir)
	if err != nil {
		return dir
	}
	return abs
}

// stdinIsTTY 判断 CLI 是不是人在终端里跑（后端转发时 stdin 是管道）。
func stdinIsTTY() bool {
	info, err := os.Stdin.Stat()
	return err == nil && info.Mode()&os.ModeCharDevice != 0
}

func next(args []string, i int) (string, int) {
	if i+1 < len(args) {
		return args[i+1], i + 1
	}
	return "", i
}

func trunc(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "..."
}
