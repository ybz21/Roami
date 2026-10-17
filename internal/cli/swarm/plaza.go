package swarm

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"

	swarmcore "github.com/ybz21/Roami/internal/swarm"
	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// plazaAuthor infers the author from the current tmux session (mirrors _plaza_author).
func plazaAuthor(rt runtime.Runtime, st *swarmcore.Store, swarm string) string {
	sname := st.Name(swarm)
	sess := strings.TrimSpace(out(rt.TmuxOutput("display-message", "-p", "#{session_name}")))
	if sess == "" {
		return "human"
	}
	if sup := st.MetaGet(swarm, "supervisor"); sup != "" && sess == sup {
		return "leader"
	}
	// 会话名是 id，身份要从展示名(@roam_name)认：指挥叫 cc-<群>，成员叫 <群>-<成员>。
	label := rt.SessionLabel(sess)
	if sess == "cc-"+sname || label == "cc-"+sname {
		return "leader"
	}
	if sname != "" && strings.HasPrefix(label, sname+"-") {
		return strings.TrimPrefix(label, sname+"-")
	}
	return "human"
}

func mentionRe(who string) *regexp.Regexp {
	return regexp.MustCompile(`(^|\s)@` + regexp.QuoteMeta(who) + `($|[\s[:punct:]])`)
}

func cmdSay(rt runtime.Runtime, st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 2 {
		ui.Err(w, "用法: roami session swarm say <群> [--as 成员] [--to 目标] [--kind 类型] <消息>")
		return fmt.Errorf("usage")
	}
	swarm := args[0]
	rest := args[1:]
	if !st.Exists(swarm) {
		ui.Err(w, "蜂群不存在: %s", swarm)
		return fmt.Errorf("not found")
	}
	as, to, kind, reStr := "", "", "note", ""
	var parts []string
	for i := 0; i < len(rest); i++ {
		switch rest[i] {
		case "--as":
			as, i = next(rest, i)
		case "--to":
			to, i = next(rest, i)
		case "--kind":
			kind, i = next(rest, i)
		case "--re":
			reStr, i = next(rest, i)
		default:
			parts = append(parts, rest[i])
		}
	}
	text := strings.Join(parts, " ")
	if text == "" {
		ui.Err(w, "消息不能为空")
		return fmt.Errorf("empty")
	}
	if to != "" {
		if to == "master" || to == "lead" {
			to = "leader"
		}
		if !mentionRe(to).MatchString(text) {
			text = "@" + to + " " + text
		}
	}
	author := as
	if author == "" {
		author = plazaAuthor(rt, st, swarm)
	}
	if author == "master" || author == "lead" {
		author = "leader"
	}
	var rePtr *int
	if n, err := strconv.Atoi(reStr); err == nil {
		rePtr = &n
	}
	id, err := st.AddPost(swarm, author, kind, rePtr, text)
	if err != nil {
		return err
	}
	ui.Ok(w, "#%d 已发布 %s", id, ui.Dim("("+author+"/"+kind+")"))
	if to != "" && to != "human" {
		st.TouchBusy(swarm, to)
	}
	if mentionRe("all").MatchString(text) {
		st.TouchBusy(swarm, "all")
	}
	if mentionRe("leader").MatchString(text) || mentionRe("master").MatchString(text) || mentionRe("lead").MatchString(text) {
		st.TouchBusy(swarm, "leader")
	}
	for _, m := range st.ActiveMembers(swarm) {
		if mentionRe(m).MatchString(text) {
			st.TouchBusy(swarm, m)
		}
	}
	notifyMaster(rt, st, swarm, id, author, kind, text, w)
	return nil
}

// notifyMaster pings the leader session when a post needs attention (mirrors _plaza_notify_master).
func notifyMaster(rt runtime.Runtime, st *swarmcore.Store, swarm string, postID int, author, kind, text string, w io.Writer) {
	if os.Getenv("TTMUX_SWARM_NOTIFY_MASTER") == "0" {
		return
	}
	if author == "leader" || author == "master" {
		return
	}
	relevant := author == "human" || kind == "ask" || kind == "block" ||
		mentionRe("leader").MatchString(text) || mentionRe("master").MatchString(text) || mentionRe("all").MatchString(text)
	if !relevant {
		return
	}
	target := masterSession(rt, st, swarm)
	if target == "" {
		return
	}
	sname := st.Name(swarm)
	notice := fmt.Sprintf("广场有新消息需要你处理：#%d (%s/%s) %s\n\n请先执行：\nroami session swarm listen %s --as leader --once\n\n然后判断是否需要回复 human、重开/新建卡片、派活或验收。处理结果请用 swarm say --kind decide/ask --re %d 回写广场。",
		postID, author, kind, text, sname, postID)
	sendPromptSubmit(rt, target, notice)
	ui.Info(w, "已通知 Leader 会话 %s 处理 #%d", ui.Bold(target), postID)
}

// masterSession 找蜂群的指挥会话名(= 会话 id)。meta.supervisor 存的就是会话名
// （老库里可能还是 cc-<群> 这样的名字，ResolveAlive 一并兜住）；再不行按展示名
// cc-<群> 现查，最后退到 leader 角色的成员会话。
func masterSession(rt runtime.Runtime, st *swarmcore.Store, swarm string) string {
	sname := st.Name(swarm)
	if sup := st.MetaGet(swarm, "supervisor"); sup != "" {
		if s := rt.ResolveAlive(sup); rt.HasSession(s) {
			return s
		}
	}
	if sname != "" {
		if s := rt.Resolve("cc-" + sname); rt.HasSession(s) {
			return s
		}
	}
	for _, m := range st.LeaderMembers(swarm) {
		if s := st.MemberSession(swarm, m); rt.HasSession(s) {
			return s
		}
	}
	return ""
}

// sendPromptSubmit pastes a multi-line prompt into a TUI and submits it
// (mirrors _tmux_send_prompt_submit). Delegates to the shared runtime helper
// so `roami session send`、广场通知、hostapi 走同一条提交路径。
func sendPromptSubmit(rt runtime.Runtime, target, message string) {
	rt.SendPromptSubmit("="+target+":", message)
}

func cmdFeed(rt runtime.Runtime, st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 1 {
		ui.Err(w, "用法: roami session swarm feed <群> [-n N] [--from 成员] [--kind 类型] [--since id] [--json]")
		return fmt.Errorf("usage")
	}
	swarm := args[0]
	if !st.Exists(swarm) {
		ui.Err(w, "蜂群不存在: %s", swarm)
		return fmt.Errorf("not found")
	}
	n, from, kind, since, jsonOut := 30, "", "", 0, false
	rest := args[1:]
	for i := 0; i < len(rest); i++ {
		switch rest[i] {
		case "-n", "--lines":
			v, j := next(rest, i)
			i = j
			if x, err := strconv.Atoi(v); err == nil {
				n = x
			}
		case "--from":
			from, i = next(rest, i)
		case "--kind":
			kind, i = next(rest, i)
		case "--since":
			v, j := next(rest, i)
			i = j
			since, _ = strconv.Atoi(v)
		case "--json":
			jsonOut = true
		}
	}
	posts, err := st.Feed(swarm, n, from, kind, since)
	if err != nil {
		return err
	}
	if jsonOut {
		if posts == nil {
			posts = []swarmcore.Post{}
		}
		return json.NewEncoder(w).Encode(posts)
	}
	p := ui.P()
	fmt.Fprintln(w)
	fmt.Fprintf(w, "  %s◆%s %s\n", p.Magenta, p.Reset, ui.Bold("广场: "+st.Name(swarm)))
	fmt.Fprintf(w, "  %s%s%s\n", p.Dim, strings.Repeat("─", 50), p.Reset)
	if len(posts) == 0 {
		fmt.Fprintf(w, "  %s(还没有消息，用 roami session swarm say %s \"...\")%s\n", p.Dim, swarm, p.Reset)
	} else {
		renderPosts(w, posts)
	}
	fmt.Fprintln(w)
	return nil
}

func cmdWatch(rt runtime.Runtime, st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: roami session swarm watch <name>")
	}
	swarm := args[0]
	if !st.Exists(swarm) {
		ui.Err(w, "蜂群不存在: %s", swarm)
		return fmt.Errorf("not found")
	}
	_ = cmdFeed(rt, st, []string{swarm, "-n", "10"}, w)
	fmt.Fprintf(w, "  %s── 跟随中（Ctrl-C 退出）──%s\n", ui.P().Dim, ui.P().Reset)
	last := st.MaxPostID(swarm)
	for {
		posts, err := st.PostsSince(swarm, last)
		if err == nil && len(posts) > 0 {
			renderPosts(w, posts)
			last = posts[len(posts)-1].ID
		}
		time.Sleep(2 * time.Second)
	}
}

func kindIcon(kind string) string {
	p := ui.P()
	switch kind {
	case "broadcast":
		return "📢"
	case "done":
		return p.Green + "✔" + p.Reset
	case "ask":
		return p.Yellow + "?" + p.Reset
	case "decide":
		return p.Cyan + "◎" + p.Reset
	case "block":
		return p.Red + "!" + p.Reset
	default:
		return p.Dim + "·" + p.Reset
	}
}

func renderPosts(w io.Writer, posts []swarmcore.Post) {
	p := ui.P()
	for _, post := range posts {
		var who string
		switch post.Author {
		case "leader", "master":
			who = p.Magenta + "◆ " + post.Author + p.Reset
		case "human":
			who = p.Blue + "● " + post.Author + p.Reset
		default:
			who = p.Green + "● " + post.Author + p.Reset
		}
		reref := ""
		if re := reString(post.Re); re != "" {
			reref = " " + p.Dim + "⤷#" + re + p.Reset
		}
		hhmm := ""
		if len(post.TS) >= 16 {
			hhmm = post.TS[11:16]
		}
		fmt.Fprintf(w, "  %s#%d %s%s  %s  %s%s %s\n", p.Dim, post.ID, hhmm, p.Reset, who, kindIcon(post.Kind), reref, post.Text)
	}
}

func reString(re any) string {
	switch t := re.(type) {
	case int:
		return strconv.Itoa(t)
	case int64:
		return strconv.FormatInt(t, 10)
	case nil:
		return ""
	default:
		return fmt.Sprintf("%v", t)
	}
}
