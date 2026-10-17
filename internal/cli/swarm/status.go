package swarm

import (
	"fmt"
	"io"
	"strings"

	"github.com/ybz21/Roami/internal/cli/group"
	swarmcore "github.com/ybz21/Roami/internal/swarm"
	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// cmdStatusText renders the human-readable swarm status (mirrors _swarm_status).
// Unlike the shell version it does not auto-activate pending members — status is
// a read; unlocking happens on `swarm done`/`swarm activate`.
func cmdStatusText(rt runtime.Runtime, st *swarmcore.Store, name string, w io.Writer) error {
	if !st.Exists(name) {
		ui.Err(w, "蜂群不存在: %s", name)
		return fmt.Errorf("not found")
	}
	p := ui.P()
	stt, err := swarmcore.Status(name, st.Options())
	if err != nil {
		return err
	}
	fmt.Fprintln(w)
	fmt.Fprintf(w, "  %s◆%s %s   %s[%s]%s\n", p.Magenta, p.Reset, ui.Bold("蜂群: "+name), p.Dim, orStr(stt.Status, "planning"), p.Reset)
	if stt.Goal != "" {
		fmt.Fprintf(w, "    %s目标:%s %s\n", p.Dim, p.Reset, stt.Goal)
	}
	if stt.Dir != "" {
		fmt.Fprintf(w, "    %s目录:%s %s\n", p.Dim, p.Reset, stt.Dir)
	}
	if stt.Supervisor != "" {
		fmt.Fprintf(w, "    %s指挥:%s %s%s%s\n", p.Dim, p.Reset, p.Magenta, stt.Supervisor, p.Reset)
	}
	if stt.Created != "" {
		fmt.Fprintf(w, "    %s创建:%s %s%s%s\n", p.Dim, p.Reset, p.Dim, stt.Created, p.Reset)
	}
	for _, m := range stt.Members {
		if m.Deps != "" {
			fmt.Fprintf(w, "    %s└ %s 依赖→ %s%s\n", p.Dim, m.Name, m.Deps, p.Reset)
		}
	}
	// per-session detail via the group renderer (members are group sessions)
	if rt.GroupExists(name) {
		_ = group.Status(rt, name, w)
	} else if len(stt.Pending) == 0 {
		fmt.Fprintf(w, "    %s(还没有成员，用 swarm add 加成员)%s\n", p.Dim, p.Reset)
	}
	if len(stt.Pending) > 0 {
		fmt.Fprintf(w, "  %s── 挂起(等依赖) ──%s\n", p.Dim, p.Reset)
		for _, pd := range stt.Pending {
			fmt.Fprintf(w, "  %s%s%s %s %s挂起%s  %s依赖→ %s%s\n",
				p.Yellow, ui.IconRun, p.Reset, ui.Bold(name+"-"+pd.Name), p.Yellow, p.Reset, p.Dim, pd.Deps, p.Reset)
		}
	}
	if len(stt.DoneMarked) > 0 {
		fmt.Fprintf(w, "  %s✔ 已标记完成: %s%s\n", p.Dim, strings.Join(stt.DoneMarked, ","), p.Reset)
	}
	// board summary
	if counts, total, err := st.ColCount(name); err == nil && total > 0 {
		var seg []string
		for _, c := range swarmcore.BoardCols {
			if counts[c] > 0 {
				seg = append(seg, fmt.Sprintf("%s %d", swarmcore.ColLabel(c), counts[c]))
			}
		}
		fmt.Fprintf(w, "  %s── 看板 ──%s  %s   %s(roami session swarm board %s)%s\n",
			p.Dim, p.Reset, strings.Join(seg, "  "), p.Dim, name, p.Reset)
	}
	// plaza recent 3
	if posts, err := st.Feed(name, 3, "", "", 0); err == nil && len(posts) > 0 {
		fmt.Fprintf(w, "  %s── 广场(最近3条) ──%s   %s(roami session swarm feed %s)%s\n", p.Dim, p.Reset, p.Dim, name, p.Reset)
		renderPosts(w, posts)
	}
	return nil
}
