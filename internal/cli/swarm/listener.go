package swarm

import (
	"fmt"
	"io"
	"regexp"
	"strconv"
	"strings"
	"time"

	swarmcore "github.com/ybz21/Roami/internal/swarm"
	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// relevance scores a post for a listener (mirrors _listener_relevance).
func relevance(who, author, kind, text string, cardRe *regexp.Regexp) string {
	if who == "leader" || who == "master" {
		if author == "human" || mentionRe("leader").MatchString(text) ||
			mentionRe("master").MatchString(text) || mentionRe("all").MatchString(text) {
			return "HIGH"
		}
		return "watch"
	}
	if mentionRe(who).MatchString(text) {
		return "HIGH"
	}
	if mentionRe("all").MatchString(text) {
		return "all"
	}
	if cardRe != nil && cardRe.MatchString(text) {
		return "card"
	}
	if (author == "leader" || author == "master") && (kind == "decide" || kind == "broadcast") {
		return "leader"
	}
	return ""
}

func cmdListen(rt runtime.Runtime, st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 1 {
		ui.Err(w, "用法: roami session swarm listen <群> [--as leader|成员] [--once] [--mentions]")
		return fmt.Errorf("usage")
	}
	swarm := args[0]
	if !st.Exists(swarm) {
		ui.Err(w, "蜂群不存在: %s", swarm)
		return fmt.Errorf("not found")
	}
	who, once, mentions, advance, interval, n := "leader", false, false, true, 10, 50
	rest := args[1:]
	for i := 0; i < len(rest); i++ {
		switch rest[i] {
		case "--as":
			who, i = next(rest, i)
		case "--once":
			once = true
		case "--mentions":
			mentions = true
		case "--no-advance":
			advance = false
		case "--interval":
			v, j := next(rest, i)
			i = j
			if x, err := strconv.Atoi(v); err == nil {
				interval = x
			}
		case "-n", "--lines":
			v, j := next(rest, i)
			i = j
			if x, err := strconv.Atoi(v); err == nil {
				n = x
			}
		}
	}
	if once {
		return listenEmit(rt, st, swarm, who, mentions, advance, n, w)
	}
	for {
		_ = listenEmit(rt, st, swarm, who, mentions, advance, n, w)
		time.Sleep(time.Duration(interval) * time.Second)
	}
}

func listenEmit(rt runtime.Runtime, st *swarmcore.Store, swarm, who string, mentions, advance bool, n int, w io.Writer) error {
	if who == "" {
		who = "leader"
	}
	if who == "master" || who == "lead" {
		who = "leader"
	}
	p := ui.P()
	last := st.ListenerLastGet(swarm, who)

	var cardRe *regexp.Regexp
	if who != "leader" {
		cards, _ := st.Cards(swarm, "", who)
		var ids []string
		for _, c := range cards {
			ids = append(ids, regexp.QuoteMeta(c.ID))
		}
		if len(ids) > 0 {
			cardRe = regexp.MustCompile(`(^|[\s#])(` + strings.Join(ids, "|") + `)($|[\s[:punct:]])`)
		}
	}

	posts, _ := st.Feed(swarm, n, "", "", last)
	fmt.Fprintln(w)
	fmt.Fprintf(w, "  %s◆%s %s  %sas=%s since=#%d%s\n", p.Magenta, p.Reset, ui.Bold("监听: "+st.Name(swarm)), p.Dim, who, last, p.Reset)
	fmt.Fprintf(w, "  %s%s%s\n", p.Dim, strings.Repeat("─", 50), p.Reset)
	maxID, shown := last, 0
	if len(posts) == 0 {
		fmt.Fprintf(w, "  %s(没有新广场消息)%s\n", p.Dim, p.Reset)
	} else {
		for _, post := range posts {
			if post.ID > maxID {
				maxID = post.ID
			}
			rel := relevance(who, post.Author, post.Kind, post.Text, cardRe)
			if mentions && rel == "" {
				continue
			}
			var whoLabel string
			switch post.Author {
			case "leader", "master":
				whoLabel = p.Magenta + "◆ " + post.Author + p.Reset
			case "human":
				whoLabel = p.Blue + "● " + post.Author + p.Reset
			default:
				whoLabel = p.Green + "● " + post.Author + p.Reset
			}
			reref := ""
			if re := reString(post.Re); re != "" {
				reref = " " + p.Dim + "⤷#" + re + p.Reset
			}
			hhmm := ""
			if len(post.TS) >= 16 {
				hhmm = post.TS[11:16]
			}
			tag := ""
			if rel != "" {
				tag = " " + p.Yellow + "[" + rel + "]" + p.Reset
			}
			fmt.Fprintf(w, "  %s#%d %s%s%s  %s  %s%s %s\n", p.Dim, post.ID, hhmm, p.Reset, tag, whoLabel, kindIcon(post.Kind), reref, post.Text)
			shown++
		}
		if shown == 0 {
			fmt.Fprintf(w, "  %s(有新消息，但没有 @%s/@all/相关卡片消息)%s\n", p.Dim, who, p.Reset)
		}
	}

	fmt.Fprintf(w, "\n  %s── 状态摘要 ──%s\n", p.Dim, p.Reset)
	statusSummary(st, swarm, w)
	fmt.Fprintf(w, "  %s── 看板摘要 ──%s\n", p.Dim, p.Reset)
	_ = cmdBoard(st, []string{swarm}, w)

	if advance && maxID > last {
		_ = st.ListenerLastSet(swarm, who, maxID)
		fmt.Fprintf(w, "  %s游标已推进到 #%d%s\n", p.Dim, maxID, p.Reset)
	}
	return nil
}

// statusSummary prints a compact member/pending overview for the listener.
func statusSummary(st *swarmcore.Store, swarm string, w io.Writer) {
	s, err := swarmcore.Status(swarm, st.Options())
	if err != nil {
		return
	}
	p := ui.P()
	for _, m := range s.Members {
		fmt.Fprintf(w, "  %s· %s%s %s[%s]%s %s\n", p.Dim, m.Name, p.Reset, p.Dim, m.Status, p.Reset, trunc(m.Task, 50))
	}
	if len(s.Pending) > 0 {
		names := make([]string, 0, len(s.Pending))
		for _, pd := range s.Pending {
			names = append(names, pd.Name)
		}
		fmt.Fprintf(w, "  %s挂起: %s%s\n", p.Dim, strings.Join(names, ", "), p.Reset)
	}
}
