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
	if len(args) > 1 {
		return fmt.Errorf("usage: roami session nw [name]")
	}
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
	if len(args) != 0 {
		return fmt.Errorf("usage: roami session lw")
	}
	p := ui.P()
	out, err := rt.TmuxOutput("list-windows", "-F", "#{window_index}\t#{window_name}\t#{window_active}")
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
	if len(args) > 1 {
		return fmt.Errorf("usage: roami session kw [window]")
	}
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
	direction := "-v"
	if len(args) > 1 || len(args) == 1 && args[0] != "-h" && args[0] != "-v" {
		return fmt.Errorf("usage: roami session split [-h|-v]")
	}
	if len(args) == 1 {
		direction = args[0]
	}
	if err := rt.Tmux("split-window", direction); err != nil {
		return err
	}
	ui.Ok(w, "窗格已分割")
	return nil
}

// KillPane mirrors the `kp` case.
func KillPane(rt runtime.Runtime, args []string, w io.Writer) error {
	if len(args) > 1 {
		return fmt.Errorf("usage: roami session kp [pane]")
	}
	native := []string{"kill-pane"}
	if len(args) == 1 {
		native = append(native, "-t", args[0])
	}
	if err := rt.Tmux(native...); err != nil {
		return err
	}
	ui.Ok(w, "窗格已关闭")
	return nil
}
