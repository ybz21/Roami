package session

import (
	"fmt"
	"io"
	"strings"

	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// NewWindow mirrors the `nw` case.
func NewWindow(rt runtime.Runtime, args []string, w io.Writer) error {
	if len(args) >= 1 {
		if err := rt.Tmux("new-window", "-n", args[0]); err != nil {
			return err
		}
		ui.Ok(w, "新窗口 %s", ui.Bold(args[0]))
		return nil
	}
	if err := rt.Tmux("new-window"); err != nil {
		return err
	}
	ui.Ok(w, "新窗口已创建")
	return nil
}

// ListWindows mirrors the `lw` case.
func ListWindows(rt runtime.Runtime, args []string, w io.Writer) error {
	p := ui.P()
	out, err := rt.TmuxOutput(append([]string{"list-windows", "-F", "#{window_index}\t#{window_name}\t#{window_active}"}, args...)...)
	fmt.Fprintln(w)
	if err != nil && strings.TrimSpace(out) == "" {
		ui.Err(w, "无法列出窗口")
		return nil
	}
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		parts := strings.Split(line, "\t")
		if len(parts) < 3 {
			continue
		}
		act := ""
		if parts[2] == "1" {
			act = " " + p.Green + "[活跃]" + p.Reset
		}
		fmt.Fprintf(w, "   %s %s  %s%s\n", ui.IconWindow, ui.Bold(parts[0]), parts[1], act)
	}
	fmt.Fprintln(w)
	return nil
}

// KillWindow mirrors the `kw` case.
func KillWindow(rt runtime.Runtime, args []string, w io.Writer) error {
	var err error
	if len(args) >= 1 {
		err = rt.Tmux("kill-window", "-t", args[0])
	} else {
		err = rt.Tmux("kill-window")
	}
	if err != nil {
		return err
	}
	ui.Ok(w, "窗口已关闭")
	return nil
}

// Split mirrors the `sp`/split case (default vertical).
func Split(rt runtime.Runtime, args []string, w io.Writer) error {
	if len(args) >= 1 && args[0] == "-h" {
		if err := rt.Tmux(append([]string{"split-window", "-h"}, args[1:]...)...); err != nil {
			return err
		}
		ui.Ok(w, "水平分割")
		return nil
	}
	rest := args
	if len(args) >= 1 && args[0] == "-v" {
		rest = args[1:]
	}
	if err := rt.Tmux(append([]string{"split-window", "-v"}, rest...)...); err != nil {
		return err
	}
	ui.Ok(w, "垂直分割")
	return nil
}

// KillPane mirrors the `kp` case.
func KillPane(rt runtime.Runtime, args []string, w io.Writer) error {
	if err := rt.Tmux(append([]string{"kill-pane"}, args...)...); err != nil {
		return err
	}
	ui.Ok(w, "窗格已关闭")
	return nil
}
