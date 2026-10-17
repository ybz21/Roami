// subSession 原语：fork / children / parent / ls --tree。
// 设计见 docs/design/web/07-worktree.md §2.1/§2.2 —— tmux 会话保持平坦，
// parent 只是 meta.db sessions 表上的字段（PPID），树是投影。
// ttmux 不理解 worktree：--dir 永远只是普通工作目录。
package session

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"

	"github.com/ybz21/Roami/internal/sessionstore"
	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// CurrentSession 返回当前所处 tmux 会话名（不在 tmux 里返回空）。
func CurrentSession(rt runtime.Runtime) string {
	if os.Getenv("TMUX") == "" {
		return ""
	}
	out, err := rt.TmuxOutput("display-message", "-p", "#S")
	if err != nil {
		return ""
	}
	return strings.TrimSpace(out)
}

// paneCwd 返回会话活动 pane 的 cwd。
// 注意 display-message 对 "=name" 精确目标会静默输出空串，须走 list-panes。
func paneCwd(rt runtime.Runtime, sess string) string {
	out, err := rt.TmuxOutput("list-panes", "-t", "="+sess, "-F", "#{pane_active}\t#{pane_current_path}")
	if err != nil {
		return ""
	}
	first := ""
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		active, cwd, ok := strings.Cut(line, "\t")
		if !ok {
			continue
		}
		if first == "" {
			first = cwd
		}
		if active == "1" {
			return cwd
		}
	}
	return first
}

// Fork 处理 `roami session fork [<父>] <子> [--dir <path>] [--detach] [--json]`。
// 子继承父的 cwd（可被 --dir 覆盖）与全局 env；meta 记 parent。
func Fork(rt runtime.Runtime, meta *sessmeta.Store, args []string, w io.Writer) error {
	var pos []string
	dir, detach, asJSON := "", false, false
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--dir", "-c":
			if i+1 < len(args) {
				dir = args[i+1]
				i++
			}
		case "--detach", "-d":
			detach = true
		case "--json":
			asJSON = true
		default:
			pos = append(pos, args[i])
		}
	}
	// child 是**展示名**：子会话本身叫 id，名字只写进 @roam_name（可与别人重名）。
	var parent, childLabel string
	switch len(pos) {
	case 1:
		parent, childLabel = CurrentSession(rt), pos[0]
		if parent == "" {
			return fmt.Errorf("not inside tmux: specify parent explicitly (roami session fork <parent> <child>)")
		}
	case 2:
		parent, childLabel = rt.Resolve(pos[0]), pos[1]
	default:
		return fmt.Errorf("usage: roami session fork [<parent>] <child> [--dir <path>] [--detach] [--json]")
	}
	if !rt.HasSession(parent) {
		return fmt.Errorf("parent session not found: %s", parent)
	}
	if dir == "" {
		dir = paneCwd(rt, parent)
	}
	rt.SetGlobalEnv()
	child, err := rt.CreateSession(runtime.CreateOpts{Label: childLabel, Dir: dir})
	if err != nil {
		return err
	}
	rt.InjectEnv(child)
	if err := meta.Put(sessmeta.Row{Session: child, Parent: parent, CreatedBy: "fork", InitialCwd: dir}); err != nil {
		// meta 失败不回滚会话（会话可用只是没了 parent 关系），但要让调用方知道
		ui.Warn(w, "会话已创建但写入 parent 元数据失败: %v", err)
	}
	if asJSON {
		return json.NewEncoder(w).Encode(map[string]string{"session": child, "label": runtime.SanitizeLabel(childLabel), "parent": parent, "cwd": dir})
	}
	ui.Ok(w, "fork %s → %s (cwd %s)", ui.Bold(Display(rt, parent)), ui.Bold(Display(rt, child)), dir)
	if !detach && IsTerminal() {
		return rt.Tmux("attach-session", "-t", "="+child)
	}
	return nil
}

// Children 输出直接子会话（--json 为数组）。
func Children(rt runtime.Runtime, meta *sessmeta.Store, args []string, w io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: roami session children <session> [--json]")
	}
	meta.Reconcile(aliveSet(rt))
	kids := meta.Children(rt.Resolve(args[0]))
	if has(args, "--json") {
		if kids == nil {
			kids = []string{}
		}
		return json.NewEncoder(w).Encode(kids)
	}
	for _, k := range kids {
		fmt.Fprintln(w, k)
	}
	return nil
}

// ParentCmd 处理 `roami session parent set|clear|get <child> [<parent>]`。
func ParentCmd(rt runtime.Runtime, meta *sessmeta.Store, args []string, w io.Writer) error {
	if len(args) < 2 {
		return fmt.Errorf("usage: roami session parent set <child> <parent> | clear <child> | get <child>")
	}
	op, child := args[0], rt.Resolve(args[1])
	switch op {
	case "set":
		if len(args) < 3 {
			return fmt.Errorf("usage: roami session parent set <child> <parent>")
		}
		parent := rt.Resolve(args[2])
		if !rt.HasSession(parent) {
			return fmt.Errorf("parent session not found: %s", parent)
		}
		if !rt.HasSession(child) {
			return fmt.Errorf("session not found: %s", child)
		}
		if err := meta.SetParent(child, parent); err != nil {
			return err
		}
		ui.Ok(w, "parent(%s) = %s", ui.Bold(child), ui.Bold(parent))
	case "clear":
		if err := meta.SetParent(child, ""); err != nil {
			return err
		}
		ui.Ok(w, "parent(%s) 已清空", ui.Bold(child))
	case "get":
		fmt.Fprintln(w, meta.Parent(child))
	default:
		return fmt.Errorf("unknown parent op: %s", op)
	}
	return nil
}

type treeNode struct {
	Name string `json:"name"`
	// Label 展示名（@roam_name）；ID 会话 id（会话名本身，老会话现算派生）；
	// TmuxID 是原始 $142（内部键：meta.db 主键、session-homes 的键）。
	Label        string      `json:"label,omitempty"`
	ID           string      `json:"id,omitempty"`
	TmuxID       string      `json:"tmux_id,omitempty"`
	Windows      int         `json:"windows"`
	Created      string      `json:"created"`
	Attached     int         `json:"attached"`
	LastActivity string      `json:"last_activity"`
	Cwd          string      `json:"cwd,omitempty"`
	Parent       string      `json:"parent,omitempty"`
	CreatedBy    string      `json:"created_by,omitempty"`
	Children     []*treeNode `json:"children,omitempty"`
	// 与 sessionInfo 同义：live | dormant，以及休眠会话点开后能不能接回对话。
	State     string `json:"state,omitempty"`
	Agent     string `json:"agent,omitempty"`
	Resumable bool   `json:"resumable,omitempty"`
	Repo      string `json:"repo,omitempty"`
	// Mem 会话此刻吃了多少。**会话列表走的就是这条树接口**，漏了这一列，
	// 内存条在最该出现的地方永远画不出来。
	Mem *memInfo `json:"mem,omitempty"`
}

// TreeJSON 输出 parent 投影的会话森林（含每会话活动 pane cwd）。
func TreeJSON(rt runtime.Runtime, meta *sessmeta.Store, exclude map[string]bool, w io.Writer) error {
	nodes, roots := buildTree(rt, meta, exclude)
	_ = nodes
	if roots == nil {
		roots = []*treeNode{}
	}
	return json.NewEncoder(w).Encode(roots)
}

// Tree 人类可读树。
func Tree(rt runtime.Runtime, meta *sessmeta.Store, exclude map[string]bool, w io.Writer) error {
	_, roots := buildTree(rt, meta, exclude)
	var walk func(n *treeNode, prefix string, last bool)
	walk = func(n *treeNode, prefix string, last bool) {
		branch := "├─ "
		next := prefix + "│  "
		if last {
			branch = "└─ "
			next = prefix + "   "
		}
		if prefix == "" {
			branch, next = "", "   "
		}
		label := ui.Bold(n.Label)
		if n.ID != "" && n.ID != n.Label {
			label += ui.Dim("(" + n.ID + ")")
		}
		fmt.Fprintf(w, "%s%s%s  %s\n", prefix, branch, label, ui.Dim(n.Cwd))
		for i, c := range n.Children {
			walk(c, next, i == len(n.Children)-1)
		}
	}
	for _, r := range roots {
		walk(r, "", true)
	}
	return nil
}

// buildTree 把 Collect 给的会话集合投影成 parent 森林。
//
// **不再自己跑一遍 list-sessions**：从前它和 ListJSON 各解析一次同样的字段，
// 于是「概览里有、点进项目又没了」——加一类会话只在一处补，另一处就静默漏掉。
func buildTree(rt runtime.Runtime, meta *sessmeta.Store, exclude map[string]bool) (map[string]*treeNode, []*treeNode) {
	sessions := Collect(rt, meta, exclude)
	rows := meta.All()

	nodes := map[string]*treeNode{}
	var order []string
	for _, s := range sessions {
		n := &treeNode{
			Name: s.Name, Label: s.Label, ID: s.ID, TmuxID: s.TmuxID,
			Windows: s.Windows, Created: s.Created, Attached: s.Attached,
			LastActivity: s.LastActivity, State: s.State, Agent: s.Agent,
			Resumable: s.Resumable, Repo: s.Repo, Mem: s.Mem,
		}
		// 休眠会话没有 pane，cwd 只能取台账里记下的归属目录——项目详情页正是靠它归位。
		if s.State == "dormant" {
			n.Cwd = s.Dir
			n.CreatedBy = s.CreatedBy
			n.Parent = s.Parent
		}
		nodes[n.Name] = n
		order = append(order, n.Name)
	}

	// 活会话的 cwd 取自活动 pane（一次 list-panes -a）。休眠会话上面已经填过，不覆盖。
	if pout, err := rt.TmuxOutput("list-panes", "-a", "-F", "#{session_name}\t#{pane_active}\t#{pane_current_path}"); err == nil {
		for _, line := range strings.Split(strings.TrimSpace(pout), "\n") {
			parts := strings.Split(line, "\t")
			if len(parts) < 3 {
				continue
			}
			if n, ok := nodes[parts[0]]; ok && (n.Cwd == "" || parts[1] == "1") {
				n.Cwd = parts[2]
			}
		}
	}

	var roots []*treeNode
	for _, name := range order {
		n := nodes[name]
		if r, ok := rows[name]; ok {
			n.CreatedBy = r.CreatedBy
			if p, ok2 := nodes[r.Parent]; ok2 && r.Parent != "" {
				n.Parent = r.Parent
				p.Children = append(p.Children, n)
				continue
			}
		}
		roots = append(roots, n)
	}
	for _, n := range nodes {
		sort.Slice(n.Children, func(i, j int) bool { return n.Children[i].Name < n.Children[j].Name })
	}
	return nodes, roots
}

// KillTree 处理 `roami session kill <名> [--cascade] [--yes]`：默认孤儿收养，--cascade 级联。
// 只动 session 与 meta，不删任何目录（设计 §2.1）。
func KillTree(rt runtime.Runtime, meta *sessmeta.Store, exclude map[string]bool, args []string, w io.Writer) error {
	cascade, yes := false, false
	var pos []string
	for _, a := range args {
		switch a {
		case "--cascade":
			cascade = true
		case "--yes", "-y":
			yes = true
		default:
			pos = append(pos, a)
		}
	}
	var target string
	if len(pos) >= 1 {
		target = rt.Resolve(pos[0])
	} else {
		t, err := PickSession(rt, exclude, "关闭会话", w)
		if err != nil {
			return err
		}
		target = t
	}
	if !rt.HasSession(target) {
		ui.Err(w, "会话 %s 不存在", ui.Bold(target))
		return fmt.Errorf("session not found: %s", target)
	}
	victims := []string{target}
	if cascade {
		meta.Reconcile(aliveSet(rt))
		victims = append(victims, descendants(meta, target)...)
	}
	shown := Display(rt, target)
	if !yes {
		label := ui.Bold(shown)
		if len(victims) > 1 {
			label = fmt.Sprintf("%s 及其 %d 个子会话", ui.Bold(shown), len(victims)-1)
		}
		if !ui.Confirm("确定关闭会话 " + label + "?") {
			ui.Info(w, "已取消")
			return nil
		}
	}
	// 自底向上杀，避免中途失败留下半棵树没了 parent 记录
	for i := len(victims) - 1; i >= 0; i-- {
		v := victims[i]
		if rt.HasSession(v) {
			if err := rt.Tmux("kill-session", "-t", "="+v); err != nil {
				return err
			}
		}
		_ = meta.OnKill(v) // 非级联时：OnKill 内部把直接孩子 parent 置 NULL = 孤儿收养
	}
	if len(victims) > 1 {
		ui.Ok(w, "会话 %s 及 %d 个子会话已关闭", ui.Bold(shown), len(victims)-1)
	} else {
		ui.Ok(w, "会话 %s 已关闭", ui.Bold(shown))
	}
	return nil
}

func descendants(meta *sessmeta.Store, root string) []string {
	var out []string
	queue := meta.Children(root)
	for len(queue) > 0 {
		n := queue[0]
		queue = queue[1:]
		out = append(out, n)
		queue = append(queue, meta.Children(n)...)
	}
	return out
}

func aliveSet(rt runtime.Runtime) map[string]bool {
	set := map[string]bool{}
	for _, s := range rt.Sessions() {
		set[s] = true
	}
	return set
}

func has(args []string, flag string) bool {
	for _, a := range args {
		if a == flag {
			return true
		}
	}
	return false
}
