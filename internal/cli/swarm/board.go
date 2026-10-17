package swarm

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"

	swarmcore "github.com/ybz21/Roami/internal/swarm"
	"github.com/ybz21/Roami/internal/terminalui"
)

func cmdTask(st *swarmcore.Store, args []string, w io.Writer) error {
	action := ""
	if len(args) > 0 {
		action = args[0]
		args = args[1:]
	}
	switch action {
	case "add":
		return taskAdd(st, args, w)
	case "ls":
		return taskList(st, args, w)
	case "show":
		return taskShow(st, args, w)
	case "assign":
		return taskAssign(st, args, w)
	case "move":
		return taskMove(st, args, w)
	case "done":
		if len(args) >= 2 {
			return taskMove(st, []string{args[0], args[1], "done"}, w)
		}
		return fmt.Errorf("usage: roami session swarm task done <swarm> <card>")
	case "rm":
		return taskRm(st, args, w)
	default:
		ui.Err(w, "未知: swarm task %s  %s", action, ui.Dim("(add/ls/show/assign/move/done/rm)"))
		return fmt.Errorf("unknown task action")
	}
}

func taskAdd(st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf(`usage: roami session swarm task add <swarm> "<title>" [--desc ..][--assignee ..][--deps ..][--col ..]`)
	}
	swarm := args[0]
	rest := args[1:]
	if !st.Exists(swarm) {
		ui.Err(w, "蜂群不存在: %s", swarm)
		return fmt.Errorf("not found")
	}
	desc, assignee, deps, col := "", "", "", ""
	var parts []string
	for i := 0; i < len(rest); i++ {
		switch rest[i] {
		case "--desc":
			desc, i = next(rest, i)
		case "--assignee":
			assignee, i = next(rest, i)
		case "--deps":
			deps, i = next(rest, i)
		case "--col":
			col, i = next(rest, i)
		default:
			parts = append(parts, rest[i])
		}
	}
	title := strings.Join(parts, " ")
	if title == "" {
		ui.Err(w, "卡片标题不能为空")
		return fmt.Errorf("empty title")
	}
	if col == "" {
		if assignee != "" {
			col = "assigned"
		} else {
			col = "backlog"
		}
	}
	if !swarmcore.ColValid(col) {
		ui.Err(w, "列只能是: %s", strings.Join(swarmcore.BoardCols, " "))
		return fmt.Errorf("bad col")
	}
	id, err := st.CardAdd(swarm, title, desc, assignee, deps, col)
	if err != nil {
		return err
	}
	fmt.Fprintln(w, id) // id is the data result (stdout, for `cid=$(... )`)
	to := ""
	if assignee != "" {
		to = fmt.Sprintf("  %s→ %s%s", ui.P().Cyan, assignee, ui.P().Reset)
	}
	// confirmation goes to stderr so stdout stays just the id (mirrors _board_add >&2)
	ui.Ok(os.Stderr, "新卡 %s  %s  %s%s", ui.Bold(id), title, ui.Dim("["+col+"]"), to)
	return nil
}

func taskAssign(st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 3 {
		ui.Err(w, "用法: roami session swarm task assign <群> <卡id> <成员>")
		return fmt.Errorf("usage")
	}
	swarm, cid, who := args[0], args[1], args[2]
	if !st.Exists(swarm) {
		ui.Err(w, "蜂群不存在: %s", swarm)
		return fmt.Errorf("not found")
	}
	if !st.CardExists(swarm, cid) {
		ui.Err(w, "卡片不存在: %s", cid)
		return fmt.Errorf("no card")
	}
	if err := st.CardAssign(swarm, cid, who); err != nil {
		return err
	}
	ui.Ok(w, "%s %s→ %s%s  %s", ui.Bold(cid), ui.P().Cyan, who, ui.P().Reset, ui.Dim("[已派]"))
	return nil
}

func taskMove(st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 3 {
		ui.Err(w, "用法: roami session swarm task move <群> <卡id> <列>")
		return fmt.Errorf("usage")
	}
	swarm, cid, col := args[0], args[1], args[2]
	if !st.Exists(swarm) {
		ui.Err(w, "蜂群不存在: %s", swarm)
		return fmt.Errorf("not found")
	}
	if !swarmcore.ColValid(col) {
		ui.Err(w, "列只能是: %s", strings.Join(swarmcore.BoardCols, " "))
		return fmt.Errorf("bad col")
	}
	if !st.CardExists(swarm, cid) {
		ui.Err(w, "卡片不存在: %s", cid)
		return fmt.Errorf("no card")
	}
	old, err := st.CardMove(swarm, cid, col)
	if err != nil {
		return err
	}
	ui.Ok(w, "%s  %s", ui.Bold(cid), ui.Dim("["+old+" → "+col+"]"))
	return nil
}

func taskRm(st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 2 {
		ui.Err(w, "用法: roami session swarm task rm <群> <卡id>")
		return fmt.Errorf("usage")
	}
	swarm, cid := args[0], args[1]
	if !st.Exists(swarm) {
		ui.Err(w, "蜂群不存在: %s", swarm)
		return fmt.Errorf("not found")
	}
	if !st.CardExists(swarm, cid) {
		ui.Err(w, "卡片不存在: %s", cid)
		return fmt.Errorf("no card")
	}
	if err := st.CardRemove(swarm, cid); err != nil {
		return err
	}
	ui.Ok(w, "卡片 %s 已删除", ui.Bold(cid))
	return nil
}

func taskShow(st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 2 {
		ui.Err(w, "用法: roami session swarm task show <群> <卡id>")
		return fmt.Errorf("usage")
	}
	swarm, cid := args[0], args[1]
	if !st.Exists(swarm) {
		ui.Err(w, "蜂群不存在: %s", swarm)
		return fmt.Errorf("not found")
	}
	if !st.CardExists(swarm, cid) {
		ui.Err(w, "卡片不存在: %s", cid)
		return fmt.Errorf("no card")
	}
	c, err := st.CardGet(swarm, cid)
	if err != nil {
		return err
	}
	p := ui.P()
	fmt.Fprintln(w)
	fmt.Fprintf(w, "  %s%s%s  %s  %s\n", p.Yellow, c.ID, p.Reset, ui.Bold(c.Title), ui.Dim("["+c.Col+"]"))
	if c.Assignee != "" {
		fmt.Fprintf(w, "    %s负责:%s %s%s%s\n", p.Dim, p.Reset, p.Cyan, c.Assignee, p.Reset)
	}
	if c.Deps != "" {
		fmt.Fprintf(w, "    %s依赖卡:%s %s\n", p.Dim, p.Reset, c.Deps)
	}
	if c.Descr != "" {
		fmt.Fprintf(w, "    %s描述:%s %s\n", p.Dim, p.Reset, c.Descr)
	}
	fmt.Fprintf(w, "    %s创建 %s  更新 %s%s\n\n", p.Dim, c.Created, c.Updated, p.Reset)
	return nil
}

func taskList(st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: roami session swarm task ls <swarm> [--col ..][--assignee ..][--json]")
	}
	swarm := args[0]
	rest := args[1:]
	if !st.Exists(swarm) {
		ui.Err(w, "蜂群不存在: %s", swarm)
		return fmt.Errorf("not found")
	}
	col, who, jsonOut := "", "", false
	for i := 0; i < len(rest); i++ {
		switch rest[i] {
		case "--col":
			col, i = next(rest, i)
		case "--assignee":
			who, i = next(rest, i)
		case "--json":
			jsonOut = true
		}
	}
	cards, err := st.Cards(swarm, col, who)
	if err != nil {
		return err
	}
	if jsonOut {
		if cards == nil {
			cards = []swarmcore.Card{}
		}
		return json.NewEncoder(w).Encode(cards)
	}
	p := ui.P()
	if len(cards) == 0 {
		fmt.Fprintf(w, "  %s(无卡片)%s\n", p.Dim, p.Reset)
		return nil
	}
	for _, c := range cards {
		to := ""
		if c.Assignee != "" {
			to = fmt.Sprintf(" %s→ %s%s", p.Cyan, c.Assignee, p.Reset)
		}
		fmt.Fprintf(w, "  %s%s%s  %s[%s]%s %s%s\n", p.Yellow, c.ID, p.Reset, p.Dim, c.Col, p.Reset, c.Title, to)
	}
	return nil
}

func cmdBoard(st *swarmcore.Store, args []string, w io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: roami session swarm board <swarm> [--json]")
	}
	swarm := args[0]
	if !st.Exists(swarm) {
		ui.Err(w, "蜂群不存在: %s", swarm)
		return fmt.Errorf("not found")
	}
	if len(args) > 1 && args[1] == "--json" {
		cards, err := st.Cards(swarm, "", "")
		if err != nil {
			return err
		}
		if cards == nil {
			cards = []swarmcore.Card{}
		}
		return json.NewEncoder(w).Encode(cards)
	}
	p := ui.P()
	goal := st.MetaGet(swarm, "goal")
	fmt.Fprintln(w)
	head := ui.Bold("看板: " + st.Name(swarm))
	if goal != "" {
		head += fmt.Sprintf("    %s目标: %s%s", p.Dim, goal, p.Reset)
	}
	fmt.Fprintf(w, "  %s %s\n", ui.IconGroup, head)
	fmt.Fprintf(w, "  %s%s%s\n", p.Dim, strings.Repeat("─", 50), p.Reset)
	all, _ := st.Cards(swarm, "", "")
	byCol := map[string][]swarmcore.Card{}
	for _, c := range all {
		byCol[c.Col] = append(byCol[c.Col], c)
	}
	for _, col := range swarmcore.BoardCols {
		cards := byCol[col]
		fmt.Fprintf(w, "  %s%s%s %s(%s · %d)%s\n", p.Bold, col, p.Reset, p.Dim, swarmcore.ColLabel(col), len(cards), p.Reset)
		for _, c := range cards {
			a := ""
			if c.Assignee != "" {
				a = fmt.Sprintf("  %s→ %s%s", p.Cyan, c.Assignee, p.Reset)
			}
			d := ""
			if c.Deps != "" {
				d = fmt.Sprintf("  %sdeps: %s%s", p.Dim, c.Deps, p.Reset)
			}
			fmt.Fprintf(w, "    %s%s%s  %s%s%s\n", p.Yellow, c.ID, p.Reset, c.Title, a, d)
		}
	}
	fmt.Fprintf(w, "\n  %s共 %d 张卡%s\n\n", p.Dim, len(all), p.Reset)
	return nil
}
