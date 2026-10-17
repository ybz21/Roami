package session

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/gitcontext"
	"github.com/ybz21/Roami/internal/revive"
	"github.com/ybz21/Roami/internal/sessionstore"
	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// List renders the human-readable session table (mirrors _pretty_sessions),
// hiding swarm-owned sessions via exclude.
//
// 会话集合来自 Collect —— 与 `ls --json` / `ls --tree` 同一个出处，所以
// **休眠会话（机器重启带走的）在命令行这边也看得见**，attach 一下就回来。
func List(rt runtime.Runtime, meta *sessmeta.Store, exclude map[string]bool, w io.Writer) error {
	sessions := Collect(rt, meta, exclude)
	p := ui.P()
	fmt.Fprintln(w)
	live, dormant := 0, 0
	for _, s := range sessions {
		ts := s.Created
		created, _ := strconv.ParseInt(s.Created, 10, 64)
		if created > 0 {
			ts = time.Unix(created, 0).Format("01-02 15:04")
		}
		label := ui.Bold(s.Label)
		if s.ID != "" && s.ID != s.Label {
			label += p.Dim + "(" + s.ID + ")" + p.Reset
		}
		if s.State == "dormant" {
			hint := "休眠 · attach 即恢复"
			if s.Resumable {
				hint = "休眠 · 可接回对话"
			}
			fmt.Fprintf(w, "   %s %s  %s%s  [%s]%s\n", ui.IconSessionDormant, label, p.Dim, ts, hint, p.Reset)
			dormant++
			continue
		}
		att := ui.Dim("[空闲]")
		if s.Attached > 0 {
			att = p.Green + "[已连接]" + p.Reset
		}
		fmt.Fprintf(w, "   %s %s  %s%d 个窗口  %s%s  %s\n",
			ui.IconSession, label, p.Dim, s.Windows, ts, p.Reset, att)
		live++
	}
	if live == 0 && dormant == 0 {
		ui.Info(w, "没有活跃会话")
		return nil
	}
	fmt.Fprintln(w)
	if dormant > 0 {
		fmt.Fprintf(w, "   %s共 %d 个会话 · %d 个休眠（attach 即恢复）%s\n\n", p.Dim, live, dormant, p.Reset)
	} else {
		fmt.Fprintf(w, "   %s共 %d 个会话%s\n\n", p.Dim, live, p.Reset)
	}
	return nil
}
func PickSession(rt runtime.Runtime, exclude map[string]bool, prompt string, w io.Writer) (string, error) {
	var rows []runtime.SessionRow
	for _, s := range rt.SessionRows() {
		if !exclude[s.Name] {
			rows = append(rows, s)
		}
	}
	if len(rows) == 0 {
		ui.Err(w, "没有活跃会话")
		return "", fmt.Errorf("no sessions")
	}
	if len(rows) == 1 {
		return rows[0].Name, nil
	}
	var b strings.Builder
	fmt.Fprintf(&b, "\n   %s:\n\n", ui.Bold(prompt))
	for i, s := range rows {
		fmt.Fprintf(&b, "   %d) %s\n", i+1, s.Display())
	}
	choice, ok := ui.ReadLine(b.String() + "\n   输入编号或名称: ")
	if !ok {
		return "", fmt.Errorf("no tty")
	}
	if n, err := strconv.Atoi(choice); err == nil && n >= 1 && n <= len(rows) {
		return rows[n-1].Name, nil
	}
	return rt.Resolve(choice), nil
}

// New 处理 `roami session new [<展示名>] [--dir <path>] [--size <W>x<H>] [--detach] [--json]
// [tmux 参数…]`。
//
// 参数里的名字是**展示名**：会话本身叫 id（CreateSession 生成），名字只写进
// @roam_name。--detach/--json 供编排方（Web 后端、脚本）用：不 attach，输出
// {"session":"<id>","label":"<展示名>"}。
func New(rt runtime.Runtime, args []string, w io.Writer) error {
	opt := runtime.CreateOpts{}
	detach, asJSON, reuse := false, false, true
	var pos []string
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--dir", "-c":
			if i+1 < len(args) {
				opt.Dir = args[i+1]
				i++
			}
		case "--size":
			if i+1 < len(args) {
				opt.Width, opt.Height, _ = strings.Cut(args[i+1], "x")
				i++
			}
		case "--detach", "-d":
			detach = true
		case "--json":
			asJSON, detach = true, true
		case "--no-reuse": // 允许重名：不复用同展示名的既有会话，一律新建
			reuse = false
		default:
			pos = append(pos, args[i])
		}
	}
	if len(pos) > 0 {
		opt.Label = pos[0]
		opt.Extra = pos[1:]
	}
	result, err := Create(rt, opt, reuse)
	if err != nil {
		return err
	}
	if asJSON {
		return json.NewEncoder(w).Encode(result)
	}
	ui.Info(w, "会话 %s", ui.Bold(Display(rt, result.Session)))
	if detach {
		return nil
	}
	return rt.Tmux("attach-session", "-t", "="+result.Session)

}

type CreateResult struct {
	Session string `json:"session"`
	Label   string `json:"label"`
	Reused  string `json:"reused,omitempty"`
}

// Create is the structured entry shared by the CLI and HTTP adapters.
func Create(rt runtime.Runtime, opt runtime.CreateOpts, reuse bool) (CreateResult, error) {
	rt.SetGlobalEnv()
	if opt.Label != "" && reuse {
		if target := rt.Resolve(opt.Label); rt.HasSession(target) {
			return CreateResult{Session: target, Label: rt.SessionLabel(target), Reused: "1"}, nil
		}
	}
	sess, err := rt.CreateSession(opt)
	if err != nil {
		return CreateResult{}, err
	}
	recordNewSession(rt, sess, opt.Dir)
	return CreateResult{Session: sess, Label: rt.SessionLabel(sess)}, nil
}

// recordNewSession 给新建的会话留下**盘上的痕迹**：一行会话元数据 + 输出日志。
//
// 以前只有任务会话（spawn）、蜂群成员和插件会话做这件事，`roami session new` 和 Web
// 「新建会话」建出来的普通会话在 Roami 主目录里一个字节都不留。于是机器一重启，
// 这些会话连「存在过」都无从证明——logs/ 里没有它们的日志，meta.db 里没有它们的
// 行，用户看到的就是「项目全空了，而且查不到任何线索」。
//
// 两件事都不该让建会话失败：记不下就算了，会话本身是好的。
func recordNewSession(rt runtime.Runtime, sess, dir string) {
	if sess == "" {
		return
	}
	if dir == "" { // 没显式指定就问 tmux 要 pane 的当前目录
		// 目标必须写 `=<会话>:`——pane_current_path 是 **pane 级**属性，
		// 裸 `=<会话>` 时 tmux 静默返回空串（不报错、退出码 0），于是 dir 恒空、
		// SetHome 存了个空目录，这个会话就再也算不出项目归属了。同 #214。
		out, err := rt.TmuxOutput("display-message", "-t", "="+sess+":", "-p", "#{pane_current_path}")
		if err == nil {
			dir = strings.TrimSpace(out)
		}
	}
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	_ = meta.Put(sessmeta.Row{Session: sess, CreatedBy: "new", InitialCwd: dir})
	// 归属目录与仓库根现在就记下来：worktree 事后会被删掉，那时再从目录反推
	// 就永远推不出来了，而「这个会话属于哪个项目」正是靠仓库根认的。
	_ = meta.SetHome(sess, dir, repoRootOf(dir))
	// 名字要**有意义**且**落库**。
	//
	// 从前这里落的是 rt.SessionLabel()，而它在没设 @roam_name 时退回会话名——
	// 于是台账里存进一个「名字就是 id」的假名字，列表上是一排 2026-0812-1811-000f。
	// 没起名就用归属目录名认人，并且 tmux 那边也设上：@roam_name 随会话生死，
	// 台账 label 是会话死后唯一还认得出它的东西，两边得是同一个名字。
	if label := rt.SessionLabel(sess); label == "" || label == sess {
		if dir != "" {
			auto := filepath.Base(dir)
			_ = rt.SetSessionLabel(sess, auto)
			_ = meta.SetLabel(sess, auto)
		}
	} else {
		_ = meta.SetLabel(sess, label)
	}
	// 目标写 `=<会话>:`：`=` 关掉前缀匹配（`dev` 会命中 `dev-review`），末尾的冒号
	// 是必须的——pipe-pane 要的是 pane，裸 `=<会话>` tmux 会报 can't find pane。
	// -o：已经在管道就不重复开（fork/spawn 路径可能先开过）
	_ = rt.Tmux("pipe-pane", "-t", "="+sess+":", "-o", "cat >> '"+rt.LogFile(sess)+"'")
}

// repoRootOf 求目录所属的 git 主仓库根（worktree 会归位到主仓库，不是它自己）。
// 不是 git 目录、或者 git 不在，就返回空——这一列本来就是 best-effort。
func repoRootOf(dir string) string {
	if dir == "" {
		return ""
	}
	cmd := exec.Command("git", "-C", dir, "rev-parse",
		"--path-format=absolute", "--git-common-dir")
	cmd.Env = gitcontext.ForDirectory(os.Environ())
	out, err := cmd.Output()
	if err != nil {
		return ""
	}
	gitDir := strings.TrimSpace(string(out))
	return strings.TrimSuffix(strings.TrimSuffix(gitDir, "/"), "/.git")
}

// Attach attaches to a session (mirrors the `a`/attach case).
func Attach(rt runtime.Runtime, meta *sessmeta.Store, exclude map[string]bool, args []string, w io.Writer) error {
	var target string
	if len(args) >= 1 {
		target = rt.Resolve(args[0])
	} else {
		t, err := PickSession(rt, exclude, "附加到会话", w)
		if err != nil {
			return err
		}
		target = t
	}
	if !rt.HasSession(target) {
		// tmux 里没有，但台账可能还认得它：机器重启带走的会话在这里当场重开，
		// 然后照常 attach 下去。与 Web 端点开一个休眠会话走的是同一段代码
		// （backend/pty 那边也调 roami session db revive），命令行不该是另一套行为。
		res, err := revive.ReviveDormant(rt, meta, target)
		if err != nil {
			ui.Err(w, "会话 %s 不存在", ui.Bold(target))
			return fmt.Errorf("session not found: %s", target)
		}
		ui.Ok(w, "已恢复 %s → %s", ui.Bold(target), ui.Bold(res.Session))
		if res.Resumed != "" {
			ui.Info(w, "已接回原对话 %s", ui.Dim(res.Resumed))
		}
		target = res.Session
	}
	ui.Info(w, "附加到 %s", ui.Bold(Display(rt, target)))
	return rt.Tmux("attach-session", "-t", "="+target)
}

// Display 会话的展示口径「名字(id)」，供各命令回显用。
func Display(rt runtime.Runtime, name string) string {
	if row := rt.SessionRow(name); row.Name != "" {
		return row.Display()
	}
	return name
}

// Detach mirrors the `d`/detach case.
func Detach(rt runtime.Runtime, args []string, w io.Writer) error {
	if err := rt.Tmux(append([]string{"detach-client"}, args...)...); err != nil {
		return err
	}
	ui.Ok(w, "已分离")
	return nil
}

// Kill kills one session after confirmation (mirrors the `kill` case).
func Kill(rt runtime.Runtime, exclude map[string]bool, args []string, w io.Writer) error {
	var target string
	if len(args) >= 1 {
		target = rt.Resolve(args[0])
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
	shown := Display(rt, target)
	if !ui.Confirm("确定关闭会话 " + ui.Bold(shown) + "?") {
		ui.Info(w, "已取消")
		return nil
	}
	if err := rt.Tmux("kill-session", "-t", "="+target); err != nil {
		return err
	}
	ui.Ok(w, "会话 %s 已关闭", ui.Bold(shown))
	return nil
}

// KillAll kills every non-swarm session after confirmation.
func KillAll(rt runtime.Runtime, exclude map[string]bool, w io.Writer) error {
	var names []string
	for _, s := range rt.Sessions() {
		if !exclude[s] {
			names = append(names, s)
		}
	}
	if len(names) == 0 {
		ui.Info(w, "没有活跃会话")
		return nil
	}
	if !ui.Confirm(fmt.Sprintf("确定关闭全部 %d 个会话?", len(names))) {
		ui.Info(w, "已取消")
		return nil
	}
	for _, s := range names {
		_ = rt.Tmux("kill-session", "-t", "="+s)
	}
	ui.Ok(w, "所有普通会话已关闭")
	return nil
}

// Rename 改会话的**展示名**（@roam_name）——tmux 会话名是 id，永远不动。
// 于是改名不再牵动任何按名字定位的东西：meta 外键、logs/meta 路径、group 台账、
// 前端标签与 URL 全都不受影响，重名也随便。
func Rename(rt runtime.Runtime, meta *sessmeta.Store, exclude map[string]bool, args []string, w io.Writer) (string, string, error) {
	var target, neu string
	switch {
	case len(args) >= 2:
		target, neu = rt.Resolve(args[0]), strings.Join(args[1:], " ")
	default:
		if len(args) == 1 {
			target = rt.Resolve(args[0])
		} else {
			t, err := PickSession(rt, exclude, "重命名会话", w)
			if err != nil {
				return "", "", err
			}
			target = t
		}
		n, ok := ui.ReadLine("   新名称: ")
		if !ok || n == "" {
			ui.Err(w, "名称不能为空")
			return "", "", fmt.Errorf("empty name")
		}
		neu = n
	}
	if !rt.HasSession(target) {
		ui.Err(w, "会话 %s 不存在", ui.Bold(target))
		return "", "", fmt.Errorf("session not found: %s", target)
	}
	old := rt.SessionLabel(target)
	if err := rt.SetSessionLabel(target, neu); err != nil {
		return "", "", err
	}
	// **名字也要落台账**：@roam_name 是 tmux 会话级选项，会话一死就跟着没了。
	// 只改 tmux 的话，机器重启后这个会话在历史/休眠列表里就退回一串裸 id——
	// 用户明明起过名字，却在最需要认人的时候看不到。
	if meta != nil {
		_ = meta.SetLabel(target, runtime.SanitizeLabel(neu))
	}
	ui.Ok(w, "%s → %s%s", ui.Bold(old), ui.Bold(runtime.SanitizeLabel(neu)), ui.Dim("("+target+")"))
	return target, neu, nil
}

// Send sends a command line to a session (mirrors the top-level `send` case).
func Send(rt runtime.Runtime, exclude map[string]bool, args []string, w io.Writer) error {
	if len(args) < 1 {
		ui.Err(w, "用法: roami session send [会话名] <命令>")
		return fmt.Errorf("usage")
	}
	var target, cmdStr string
	if len(args) == 1 {
		t, err := PickSession(rt, exclude, "发送命令到", w)
		if err != nil {
			return err
		}
		target, cmdStr = t, args[0]
	} else {
		target = rt.Resolve(args[0])
		cmdStr = strings.Join(args[1:], " ")
	}
	if !rt.HasSession(target) {
		ui.Err(w, "会话 %s 不存在", ui.Bold(target))
		return fmt.Errorf("session not found: %s", target)
	}
	// 用粘贴缓冲 + 独立回车提交：TUI Agent(Claude/Codex)会把 send-keys 里
	// 尾随的 C-m 当成输入换行而非提交，导致「只打字不发送」。SendPromptSubmit
	// 走 paste-buffer 落文本再单独按回车，对多行 prompt 和 TUI 都可靠。
	// pane 目标的精确匹配要写成 "=名:"（tmux 3.4 对裸 "=名" 报 can't find pane）
	if err := rt.SendPromptSubmit("="+target+":", cmdStr); err != nil {
		return err
	}
	ui.Ok(w, "已发送到 %s: %s", ui.Bold(Display(rt, target)), ui.Dim(cmdStr))
	return nil
}

// Source reloads ~/.tmux.conf (mirrors the `source` case).
func Source(rt runtime.Runtime, w io.Writer) error {
	home, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	path := filepath.Join(home, ".tmux.conf")
	if _, err := os.Stat(path); err != nil {
		ui.Err(w, "未找到 ~/.tmux.conf")
		return fmt.Errorf("no tmux.conf")
	}
	if err := rt.Tmux("source-file", path); err != nil {
		return err
	}
	ui.Ok(w, "配置已重载")
	return nil
}
