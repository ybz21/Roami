package swarm

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/ybz21/Roami/internal/cli/spawn"
	swarmcore "github.com/ybz21/Roami/internal/swarm"
	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// launchMember spawns a member session, building the agent config from its spec.
// 会话名是 id，语义名 `<群>-<成员>` 只是展示名 → 会话名必须回写进 members.session，
// 否则会话一死（展示名随之消失）就再也找不到它的日志/pane 了。
func launchMember(rt runtime.Runtime, st *swarmcore.Store, swarm string, m swarmcore.MemberSpec, w io.Writer) (bool, error) {
	ac := spawn.DefaultAgentConfig(m.Workdir)
	if m.Type == "agent" {
		ac.Kind = m.Kind
		ac.Interactive = true
		if m.Model != "" {
			ac.Model = m.Model
		}
		if m.Perm != "" {
			ac.Permission = m.Perm
		}
	}
	created, sess, err := spawn.One(rt, swarm, m.Name, m.Type, m.Task, ac, w)
	if sess != "" {
		_ = st.SetMemberSession(swarm, m.Name, sess)
	}
	return created, err
}

// spawnCallback adapts launchMember to the core's SpawnFunc signature.
func spawnCallback(rt runtime.Runtime, st *swarmcore.Store, w io.Writer) swarmcore.SpawnFunc {
	return func(swarm string, m swarmcore.MemberSpec) (bool, error) {
		return launchMember(rt, st, swarm, m, w)
	}
}

func claudeBin() string {
	if p, err := exec.LookPath("claude"); err == nil {
		return p
	}
	return "claude"
}

func hasClaude() bool {
	_, err := exec.LookPath("claude")
	return err == nil
}

func shellQuote(s string) string { return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'" }

// adopt writes supervisor metadata and brings up (or reuses) a cc-<swarm>
// commander session. The Leader's kickoff prompt is `prompt` when non-empty —
// the web layer renders prompts/master.md.tmpl and passes it via --prompt so
// the Leader gets a real briefing (身份/目标/工作目录/可用 skill/职责) instead of
// quietly implementing the whole goal solo. When empty (terminal-only adopt),
// it falls back to the bare /cc-swarm playbook invocation (mirrors _swarm_adopt).
func adopt(rt runtime.Runtime, st *swarmcore.Store, swarm, cc, dir, prompt string, w io.Writer) error {
	if !st.Exists(swarm) {
		ui.Err(w, "蜂群不存在: %s", swarm)
		return fmt.Errorf("not found")
	}
	// cc 是指挥会话的**展示名**（默认 cc-<群>）；会话本身叫 id，
	// meta.supervisor 存的是会话名(= id)，这样会话列表/exclude 才对得上。
	if cc == "" {
		cc = "cc-" + st.Name(swarm)
	}
	// 显式给了 --dir 就记进 meta：Web 项目视图按 dir 把蜂群归到项目(issue #125)。
	// 没给就保持原值不动，避免 adopt 一次把建群时记的目录抹掉。
	if abs := absDir(dir); abs != "" {
		_ = st.MetaSet(swarm, "dir", abs)
	}
	if dir == "" {
		dir = "."
	}
	if dir != "." {
		_ = os.MkdirAll(dir, 0o755)
	}
	_ = st.MetaSet(swarm, "status", "running")
	goal := st.MetaGet(swarm, "goal")
	kickoff := strings.TrimSpace(prompt)
	if kickoff == "" {
		kickoff = "/cc-swarm --swarm " + swarm
		if goal != "" {
			kickoff += " " + goal
		}
	}
	if target := rt.Resolve(cc); rt.HasSession(target) {
		_ = st.MetaSet(swarm, "supervisor", target)
		// 已有会话：用粘贴缓冲提交（send-keys 会把多行 prompt 的换行当回车提前执行）
		sendPromptSubmit(rt, target, kickoff)
		ui.Ok(w, "已让现有会话 %s 接管蜂群 %s", ui.Bold(cc), ui.Bold(swarm))
		return nil
	}
	sess, err := rt.CreateSession(runtime.CreateOpts{Label: cc, Width: "220", Height: "50"})
	if err != nil {
		return err
	}
	_ = st.MetaSet(swarm, "supervisor", sess)
	rt.InjectEnv(sess)
	_ = rt.Tmux("pipe-pane", "-t", sess, "-o", "cat >> '"+rt.LogFile(sess)+"'")
	_ = writeEmpty(rt.LogFile(sess))
	// 把（可能多行的）kickoff 落盘再用 "$(cat …)" 注入，避免换行被 send-keys 当成回车提前执行
	bf := filepath.Join(rt.DataDir, "cc-swarm", sess+".brief.md")
	_ = os.MkdirAll(filepath.Dir(bf), 0o755)
	_ = os.WriteFile(bf, []byte(kickoff), 0o644)
	runCmd := "cd " + shellQuote(dir) + " && " + claudeBin() + " \"$(cat " + shellQuote(bf) + ")\""
	_ = rt.Tmux("send-keys", "-t", sess, runCmd, "C-m")
	ui.Ok(w, "已拉起指挥会话 %s%s 接管蜂群 %s", ui.Bold(cc), ui.Dim("("+sess+")"), ui.Bold(swarm))
	if goal != "" {
		fmt.Fprintf(w, "   %s目标已交给指挥: %s%s\n", ui.P().Dim, goal, ui.P().Reset)
	}
	return nil
}

func cmdAdopt(rt runtime.Runtime, st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: roami session swarm adopt <name> [--by <session>] [--dir <dir>] [--prompt <text>]")
	}
	swarm := args[0]
	// dir 留空表示「没给 --dir」（adopt 内部再退回 "."），这样才分得清
	// 「显式指定目录」和「沿用默认」，只有前者才写进 meta.dir
	cc, dir, prompt := "", "", ""
	for i := 1; i < len(args); i++ {
		switch args[i] {
		case "--by":
			cc, i = next(args, i)
		case "--dir":
			dir, i = next(args, i)
		case "--prompt":
			prompt, i = next(args, i)
		}
	}
	return adopt(rt, st, swarm, cc, dir, prompt, w)
}

type swarmListItem struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	Goal       string `json:"goal"`
	Status     string `json:"status"`
	Supervisor string `json:"supervisor"`
	Created    string `json:"created"`
	Dir        string `json:"dir"` // 工作目录(绝对路径, 可空)：Web 按它把蜂群归到项目
	Total      int    `json:"total"`
	Alive      int    `json:"alive"`
	Pending    int    `json:"pending"`
}

func cmdList(rt runtime.Runtime, st *swarmcore.Store, args []string, w io.Writer) error {
	jsonOut := len(args) > 0 && args[0] == "--json"
	swarms, err := st.ListSwarms()
	if err != nil {
		return err
	}
	if jsonOut {
		items := []swarmListItem{}
		for _, s := range swarms {
			total, alive := groupCounts(rt, s.Name)
			items = append(items, swarmListItem{
				ID: s.ID, Name: s.Name, Goal: s.Goal, Status: s.Status,
				Supervisor: s.Supervisor, Created: s.Created, Dir: s.Dir,
				Total: total, Alive: alive, Pending: st.PendingCount(s.Name),
			})
		}
		return json.NewEncoder(w).Encode(items)
	}
	if len(swarms) == 0 {
		ui.Info(w, "没有蜂群  %s", ui.Dim("(roami session swarm new <名> 创建)"))
		return nil
	}
	p := ui.P()
	fmt.Fprintln(w)
	for _, s := range swarms {
		total, alive := groupCounts(rt, s.Name)
		st_str := p.Dim + orStr(s.Status, "planning") + p.Reset
		switch s.Status {
		case "running":
			st_str = p.Yellow + "running" + p.Reset
		case "done":
			st_str = p.Green + "done" + p.Reset
		case "integrating":
			st_str = p.Cyan + "integrating" + p.Reset
		case "archived":
			st_str = p.Dim + "archived" + p.Reset
		}
		pend := st.PendingCount(s.Name)
		pendStr := ""
		if pend > 0 {
			pendStr = fmt.Sprintf("  %s+%d待解锁%s", p.Yellow, pend, p.Reset)
		}
		sup := ""
		if s.Supervisor != "" {
			sup = fmt.Sprintf("  %s◆%s%s", p.Magenta, s.Supervisor, p.Reset)
		}
		fmt.Fprintf(w, "   %s %s  %s%d/%d 活跃%s%s  %s%s\n",
			ui.IconGroup, ui.Bold(s.Name), p.Dim, alive, total, p.Reset, pendStr, st_str, sup)
		if s.Goal != "" {
			fmt.Fprintf(w, "       %s%s%s\n", p.Dim, s.Goal, p.Reset)
		}
	}
	fmt.Fprintf(w, "  %s钻取: roami session swarm status <群>(含看板/广场) · board <群> · feed <群>%s\n\n", p.Dim, p.Reset)
	return nil
}

func cmdSQL(st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf(`usage: roami session swarm sql <name> [--json] "SELECT ..."`)
	}
	name := args[0]
	args = args[1:]
	jsonOut := false
	if len(args) > 0 && args[0] == "--json" {
		jsonOut = true
		args = args[1:]
	}
	if len(args) < 1 || strings.TrimSpace(args[0]) == "" {
		return fmt.Errorf(`usage: roami session swarm sql <name> [--json] "SELECT ..."`)
	}
	q := args[0]
	head := strings.ToLower(strings.TrimSpace(q))
	allowed := false
	for _, pfx := range []string{"select", "pragma", "explain", "with", ".tables", ".schema"} {
		if strings.HasPrefix(head, pfx) {
			allowed = true
			break
		}
	}
	if !allowed {
		ui.Err(w, "只读逃生口：仅允许 SELECT/PRAGMA/EXPLAIN/WITH/.tables/.schema")
		return fmt.Errorf("readonly guard")
	}
	cols, rows, err := st.ReadQuery(name, q)
	if err != nil {
		return err
	}
	if jsonOut {
		out := make([]map[string]string, 0, len(rows))
		for _, r := range rows {
			m := map[string]string{}
			for i, c := range cols {
				m[c] = r[i]
			}
			out = append(out, m)
		}
		return json.NewEncoder(w).Encode(out)
	}
	fmt.Fprintln(w, strings.Join(cols, "|"))
	for _, r := range rows {
		fmt.Fprintln(w, strings.Join(r, "|"))
	}
	return nil
}

func groupCounts(rt runtime.Runtime, group string) (total, alive int) {
	sessions, _ := rt.GroupSessions(group)
	for _, s := range sessions {
		total++
		if rt.HasSession(s) {
			alive++
		}
	}
	return
}

func writeEmpty(path string) error { return os.WriteFile(path, nil, 0o644) }

func out(s string, _ error) string { return s }

func orStr(s, def string) string {
	if s == "" {
		return def
	}
	return s
}
