package session

import (
	"fmt"
	"io"
	"strings"

	ui "github.com/ybz21/Roami/internal/terminalui"
	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

// WindowCmd dispatches `roami session window <new|ls|select|kill> ...` for tmux sessions.
func WindowCmd(rt runtime.Runtime, args []string, w io.Writer) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: roami session window <new|ls|select|kill> [args...]")
	}
	sub, rest := args[0], args[1:]
	switch sub {
	case "new":
		var sessionTarget, name, dir string
		for i := 0; i < len(rest); i++ {
			switch rest[i] {
			case "-c", "--dir":
				if i+1 >= len(rest) {
					return fmt.Errorf("missing value for %s", rest[i])
				}
				i++
				dir = rest[i]
			case "-a", "--attach":
			default:
				if strings.HasPrefix(rest[i], "-") {
					return fmt.Errorf("unknown flag %q", rest[i])
				}
				if sessionTarget == "" && rt.HasSession(rest[i]) {
					sessionTarget = rest[i]
				} else if name == "" {
					name = rest[i]
				}
			}
		}
		tmuxArgs := []string{"new-window"}
		if sessionTarget != "" {
			tmuxArgs = append(tmuxArgs, "-t", "="+sessionTarget+":")
		}
		if name != "" {
			tmuxArgs = append(tmuxArgs, "-n", name)
		}
		if dir != "" {
			tmuxArgs = append(tmuxArgs, "-c", dir)
		}
		if err := rt.Tmux(tmuxArgs...); err != nil {
			return err
		}
		if name != "" {
			ui.Ok(w, "新窗口 %s", ui.Bold(name))
		} else {
			ui.Ok(w, "新窗口已创建")
		}
		return nil

	case "ls", "list":
		tmuxArgs := []string{"list-windows"}
		if len(rest) == 1 {
			tmuxArgs = append(tmuxArgs, "-t", "="+rest[0])
		} else if len(rest) > 1 {
			return fmt.Errorf("usage: roami session window ls [SESSION]")
		}
		tmuxArgs = append(tmuxArgs, "-F", "#{window_index}\t#{window_name}\t#{window_active}")
		p := ui.P()
		out, err := rt.TmuxOutput(tmuxArgs...)
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

	case "select", "switch":
		var target string
		switch len(rest) {
		case 1:
			target = rest[0]
		case 2:
			target = "=" + rest[0] + ":" + rest[1]
		default:
			return fmt.Errorf("usage: roami session window select [SESSION] <WINDOW>")
		}
		if err := rt.Tmux("select-window", "-t", target); err != nil {
			return err
		}
		ui.Ok(w, "已切换窗口 %s", ui.Bold(rest[len(rest)-1]))
		return nil

	case "kill", "rm", "close":
		tmuxArgs := []string{"kill-window"}
		switch len(rest) {
		case 0:
		case 1:
			if rt.HasSession(rest[0]) {
				tmuxArgs = append(tmuxArgs, "-t", "="+rest[0])
			} else {
				tmuxArgs = append(tmuxArgs, "-t", rest[0])
			}
		case 2:
			tmuxArgs = append(tmuxArgs, "-t", "="+rest[0]+":"+rest[1])
		default:
			return fmt.Errorf("usage: roami session window kill [SESSION] [WINDOW]")
		}
		if err := rt.Tmux(tmuxArgs...); err != nil {
			return err
		}
		ui.Ok(w, "窗口已关闭")
		return nil

	default:
		return fmt.Errorf("unknown window command %q; use roami session window --help", sub)
	}
}

// PaneCmd dispatches `roami session pane <ls|split|kill> ...` for tmux sessions.
func PaneCmd(rt runtime.Runtime, args []string, w io.Writer) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: roami session pane <ls|split|kill> [args...]")
	}
	sub, rest := args[0], args[1:]
	switch sub {
	case "ls", "list":
		tmuxArgs := []string{"list-panes"}
		if len(rest) == 1 {
			tmuxArgs = append(tmuxArgs, "-t", "="+rest[0])
		} else if len(rest) > 1 {
			return fmt.Errorf("usage: roami session pane ls [SESSION]")
		}
		tmuxArgs = append(tmuxArgs, "-F", "#{pane_id}\t#{window_index}:#{window_name}\t#{pane_active}")
		out, err := rt.TmuxOutput(tmuxArgs...)
		if err != nil && strings.TrimSpace(out) == "" {
			ui.Err(w, "无法列出窗格")
			return nil
		}
		p := ui.P()
		fmt.Fprintln(w)
		for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
			parts := strings.Split(line, "\t")
			if len(parts) < 3 {
				continue
			}
			act := ""
			if parts[2] == "1" {
				act = " " + p.Green + "[活跃]" + p.Reset
			}
			fmt.Fprintf(w, "   %s  %s%s\n", ui.Bold(parts[0]), parts[1], act)
		}
		fmt.Fprintln(w)
		return nil

	case "split":
		direction := "-h" // default right split
		var sessionTarget, dir string
		for i := 0; i < len(rest); i++ {
			switch rest[i] {
			case "--right", "--horizontal", "-H":
				direction = "-h"
			case "--down", "--vertical", "-V", "-v":
				direction = "-v"
			case "-c", "--dir":
				if i+1 >= len(rest) {
					return fmt.Errorf("missing value for %s", rest[i])
				}
				i++
				dir = rest[i]
			default:
				if strings.HasPrefix(rest[i], "-") {
					return fmt.Errorf("unknown flag %q", rest[i])
				}
				if sessionTarget == "" {
					sessionTarget = rest[i]
				}
			}
		}
		tmuxArgs := []string{"split-window", direction}
		if sessionTarget != "" {
			tmuxArgs = append(tmuxArgs, "-t", "="+sessionTarget)
		}
		if dir != "" {
			tmuxArgs = append(tmuxArgs, "-c", dir)
		}
		if err := rt.Tmux(tmuxArgs...); err != nil {
			return err
		}
		ui.Ok(w, "窗格已分割")
		return nil

	case "kill", "rm", "close":
		tmuxArgs := []string{"kill-pane"}
		switch len(rest) {
		case 0:
		case 1:
			tmuxArgs = append(tmuxArgs, "-t", rest[0])
		case 2:
			tmuxArgs = append(tmuxArgs, "-t", rest[1])
		default:
			return fmt.Errorf("usage: roami session pane kill [SESSION] [PANE]")
		}
		if err := rt.Tmux(tmuxArgs...); err != nil {
			return err
		}
		ui.Ok(w, "窗格已关闭")
		return nil

	default:
		return fmt.Errorf("unknown pane command %q; use roami session pane --help", sub)
	}
}

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
