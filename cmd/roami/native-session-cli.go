package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"text/tabwriter"
	"time"

	"github.com/google/uuid"
	app "github.com/ybz21/Roami/internal/cli"
	"github.com/ybz21/Roami/internal/cli/nativeattach"
	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessionipc"
	metadb "github.com/ybz21/Roami/internal/storage"
	"github.com/ybz21/Roami/internal/ttyraw"
)

// maybeRunNativeSessionCLI integrates native roami-sessiond sessions into `roami session`:
//   - `new`: routes to native when `--backend native`, `ROAMI_NATIVE_TERMINAL=1`, or on Windows.
//   - `ls`: merges live native sessions alongside legacy tmux sessions automatically.
//   - target commands (`a/attach/sp/kp/nw/lw/kw/capture/send/rename/kill`): auto-route to an
//     already-running native host when it owns the target session, without needing any env var.
func maybeRunNativeSessionCLI(args []string) (bool, int) {
	if len(args) == 0 {
		return false, 0
	}
	cmd, rest := args[0], args[1:]
	switch cmd {
	case "new", "ls", "a", "attach", "sp", "split", "kp", "nw", "lw", "kw", "capture", "send", "rename", "kill":
	default:
		return false, 0
	}
	if len(rest) > 0 && (rest[0] == "--help" || rest[0] == "help") {
		return false, 0
	}
	return dispatchNativeSessionCLI(cmd, rest, os.Stdin, os.Stdout, os.Stderr)
}

func extractBackendFlag(args []string) (backend string, filtered []string, err error) {
	filtered = make([]string, 0, len(args))
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if arg == "--" {
			filtered = append(filtered, args[i:]...)
			break
		}
		if arg == "--backend" {
			if i+1 >= len(args) {
				return "", nil, fmt.Errorf("missing value for --backend (use native or tmux)")
			}
			i++
			backend = strings.ToLower(strings.TrimSpace(args[i]))
			continue
		}
		if v, ok := strings.CutPrefix(arg, "--backend="); ok {
			backend = strings.ToLower(strings.TrimSpace(v))
			continue
		}
		filtered = append(filtered, arg)
	}
	if backend != "" && backend != "native" && backend != "tmux" {
		return "", nil, fmt.Errorf("unknown --backend %q (use native or tmux)", backend)
	}
	return backend, filtered, nil
}

func defaultNativeBackend() bool {
	return nativeTerminalEnabled() || runtime.GOOS == "windows"
}

func dispatchNativeSessionCLI(cmd string, args []string, in io.Reader, out, errOut io.Writer) (bool, int) {
	backendFlag, rest, err := extractBackendFlag(args)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 2
	}
	if backendFlag == "tmux" {
		return false, 0
	}

	wantNativeCreate := cmd == "new" && (backendFlag == "native" || defaultNativeBackend())
	if cmd == "new" && !wantNativeCreate {
		return false, 0
	}

	paths, err := metadb.ResolvePaths("", "")
	if err != nil {
		if wantNativeCreate || backendFlag == "native" {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		return false, 0
	}
	selfBin, _ := os.Executable()
	if selfBin != "" {
		if resolved, rerr := filepath.EvalSymlinks(selfBin); rerr == nil {
			selfBin = resolved
		}
	}
	mgr := sessionipc.NewManager(paths.Data, resolveSessiondBin(selfBin))
	defer mgr.Close()

	connCtx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	var cli *sessionipc.Client
	if wantNativeCreate || backendFlag == "native" || (cmd == "ls" && defaultNativeBackend()) {
		cli, _, err = mgr.ConnectActive(connCtx)
	} else {
		// Never spawn roami-sessiond just to probe whether an existing target lives in native.
		cli, _, err = mgr.ConnectExisting(connCtx)
	}
	cancel()
	if err != nil {
		if wantNativeCreate || backendFlag == "native" {
			fmt.Fprintf(errOut, "native terminal host unavailable: %v\n", err)
			return true, 1
		}
		return false, 0
	}

	switch cmd {
	case "new":
		return true, nativeCLICreate(cli, rest, in, out, errOut)
	case "ls":
		return nativeCLIList(cli, rest, backendFlag == "native" || runtime.GOOS == "windows", out, errOut)
	case "a", "attach":
		return nativeCLIAttach(cli, rest, in, out, errOut)
	case "sp", "split":
		return nativeCLISplit(cli, rest, out, errOut)
	case "kp":
		return nativeCLIClosePane(cli, rest, out, errOut)
	case "nw":
		return nativeCLINewWindow(cli, rest, out, errOut)
	case "lw":
		return nativeCLIListWindows(cli, rest, out, errOut)
	case "kw":
		return nativeCLICloseWindow(cli, rest, out, errOut)
	case "capture":
		return nativeCLICapture(cli, rest, out, errOut)
	case "send":
		return nativeCLISend(cli, rest, out, errOut)
	case "rename":
		return nativeCLIRename(cli, rest, out, errOut)
	case "kill":
		return nativeCLIKill(cli, rest, out, errOut)
	default:
		return false, 0
	}
}

func isReaderTTY(r io.Reader) bool {
	if f, ok := r.(*os.File); ok {
		return ttyraw.IsTerminal(f.Fd())
	}
	return false
}

func nativeCLICreate(cli *sessionipc.Client, args []string, in io.Reader, out, errOut io.Writer) int {
	spec := sessionbackend.CreateSpec{LoginShell: true}
	detach := false
	asJSON := false
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch arg {
		case "--":
			if i+1 < len(args) {
				spec.Exe = args[i+1]
				spec.Args = args[i+2:]
				spec.LoginShell = false
			}
			i = len(args)
		case "-d", "--detach":
			detach = true
		case "--json":
			asJSON, detach = true, true
		case "-c", "--dir":
			if i+1 >= len(args) {
				fmt.Fprintln(errOut, "missing value for --dir")
				return 2
			}
			i++
			spec.Dir = args[i]
		case "--label":
			if i+1 >= len(args) {
				fmt.Fprintln(errOut, "missing value for --label")
				return 2
			}
			i++
			spec.Label = args[i]
		case "--no-reuse":
		default:
			if strings.HasPrefix(arg, "-") {
				fmt.Fprintf(errOut, "unknown flag %q\n", arg)
				return 2
			}
			if spec.SessionID == "" {
				spec.SessionID = arg
			} else if spec.Dir == "" {
				spec.Dir = arg
			}
		}
	}
	if spec.Dir == "" {
		if cwd, err := os.Getwd(); err == nil {
			spec.Dir = cwd
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	ref, err := cli.Create(ctx, spec)
	cancel()
	if err != nil {
		fmt.Fprintln(errOut, err)
		return 1
	}
	if asJSON {
		_ = json.NewEncoder(out).Encode(map[string]any{
			"session": ref.SessionID,
			"label":   ref.Label,
			"backend": ref.Backend,
			"window":  ref.WindowID,
			"pane":    ref.PaneID,
		})
		return 0
	}
	// Match `roami session new` / `tmux new`: attach immediately on an interactive TTY unless -d/--detach.
	if !detach && isReaderTTY(in) {
		if err := nativeattach.Attach(context.Background(), cli, cli, nativeattach.AttachOptions{
			SessionID: ref.SessionID,
			PaneID:    ref.PaneID,
			In:        in,
			Out:       out,
			RawTTY:    true,
		}); err != nil {
			fmt.Fprintln(errOut, err)
			return 1
		}
		return 0
	}
	fmt.Fprintln(out, ref.SessionID)
	return 0
}

func nativeCLIList(cli *sessionipc.Client, args []string, nativeOnly bool, out, errOut io.Writer) (bool, int) {
	asJSON := false
	for _, a := range args {
		switch a {
		case "--json":
			asJSON = true
		case "--tree", "--live":
			if !nativeOnly {
				return false, 0
			}
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	list, err := cli.List(ctx)
	cancel()
	if err != nil {
		if nativeOnly {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		return false, 0
	}
	if !nativeOnly && len(list) == 0 && !nativeTerminalEnabled() {
		return false, 0
	}
	if asJSON {
		if list == nil {
			list = []sessionbackend.SessionSummary{}
		}
		enc := json.NewEncoder(out)
		enc.SetIndent("", "  ")
		_ = enc.Encode(list)
		return true, 0
	}
	// When not native-only, render legacy tmux sessions first so one `roami session ls` shows both.
	if !nativeOnly {
		_ = app.New().WithOutput(out).Run(append([]string{"ls"}, args...))
	}
	if len(list) == 0 {
		if nativeOnly {
			fmt.Fprintln(out, "(no native sessions)")
		}
		return true, 0
	}
	if !nativeOnly {
		fmt.Fprintln(out, "Native PTY sessions (roami-sessiond):")
	}
	tw := tabwriter.NewWriter(out, 0, 2, 2, ' ', 0)
	fmt.Fprintln(tw, "SESSION\tBACKEND\tSTATUS\tWINDOWS\tATTACHED\tDIR")
	for _, s := range list {
		name := s.ID
		if s.Label != "" && s.Label != s.ID {
			name = fmt.Sprintf("%s (%s)", s.ID, s.Label)
		}
		fmt.Fprintf(tw, "%s\t%s\t%s\t%d\t%d\t%s\n", name, s.Backend, s.Status, s.Windows, s.Attached, s.Dir)
	}
	_ = tw.Flush()
	return true, 0
}

func nativeCLIAttach(cli *sessionipc.Client, args []string, in io.Reader, out, errOut io.Writer) (bool, int) {
	var sessionID, paneID string
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--pane", "-p":
			if i+1 >= len(args) {
				fmt.Fprintln(errOut, "missing value for --pane")
				return true, 2
			}
			i++
			paneID = args[i]
		default:
			if !strings.HasPrefix(args[i], "-") && sessionID == "" {
				sessionID = args[i]
			}
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	if sessionID == "" {
		list, err := cli.List(ctx)
		cancel()
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		alive := make([]sessionbackend.SessionSummary, 0, len(list))
		for _, s := range list {
			if s.Status == sessionbackend.StatusAlive {
				alive = append(alive, s)
			}
		}
		if len(alive) == 1 {
			sessionID = alive[0].ID
		} else if len(alive) == 0 {
			return false, 0
		} else {
			fmt.Fprintln(errOut, "multiple native sessions active; specify session name:")
			for _, s := range alive {
				fmt.Fprintf(errOut, "  %s\n", s.ID)
			}
			return true, 2
		}
	} else {
		_, err := cli.Observe(ctx, sessionID)
		cancel()
		if errors.Is(err, sessionbackend.ErrSessionNotFound) {
			return false, 0
		}
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
	}

	if err := nativeattach.Attach(context.Background(), cli, cli, nativeattach.AttachOptions{
		SessionID: sessionID,
		PaneID:    paneID,
		In:        in,
		Out:       out,
		RawTTY:    true,
	}); err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	return true, 0
}

func nativeCLISplit(cli *sessionipc.Client, args []string, out, errOut io.Writer) (bool, int) {
	dir := sessionbackend.SplitHorizontal
	var sessionID, paneID, cwd string
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "-h":
			dir = sessionbackend.SplitHorizontal
		case "-v":
			dir = sessionbackend.SplitVertical
		case "--pane", "-p":
			if i+1 < len(args) {
				i++
				paneID = args[i]
			}
		case "-c", "-d", "--dir":
			if i+1 < len(args) {
				i++
				cwd = args[i]
			}
		default:
			if !strings.HasPrefix(args[i], "-") && sessionID == "" {
				sessionID = args[i]
			}
		}
	}
	if sessionID == "" {
		fmt.Fprintln(errOut, "usage: roami session sp <session> [-h|-v] [--pane ID]")
		return true, 2
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	st, err := cli.Observe(ctx, sessionID)
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	if paneID == "" {
		paneID = st.ActivePaneID
	}
	_, newPaneID, err := cli.SplitPane(ctx, sessionID, paneID, sessionbackend.SplitSpec{
		Dir: dir,
		Cwd: cwd,
	})
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	fmt.Fprintln(out, newPaneID)
	return true, 0
}

func nativeCLIClosePane(cli *sessionipc.Client, args []string, out, errOut io.Writer) (bool, int) {
	var sessionID, paneID string
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--pane", "-p":
			if i+1 < len(args) {
				i++
				paneID = args[i]
			}
		default:
			if !strings.HasPrefix(args[i], "-") {
				if sessionID == "" {
					sessionID = args[i]
				} else if paneID == "" {
					paneID = args[i]
				}
			}
		}
	}
	if sessionID == "" {
		fmt.Fprintln(errOut, "usage: roami session kp <session> [paneId]")
		return true, 2
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	st, err := cli.Observe(ctx, sessionID)
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	if paneID == "" {
		paneID = st.ActivePaneID
	}
	if _, err := cli.ClosePane(ctx, sessionID, paneID); err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	fmt.Fprintln(out, paneID)
	return true, 0
}

func nativeCLINewWindow(cli *sessionipc.Client, args []string, out, errOut io.Writer) (bool, int) {
	if len(args) < 1 {
		fmt.Fprintln(errOut, "usage: roami session nw <session> [name]")
		return true, 2
	}
	sessionID := args[0]
	var name string
	if len(args) > 1 {
		name = args[1]
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if _, err := cli.Observe(ctx, sessionID); errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	win, err := cli.NewWindow(ctx, sessionID, sessionbackend.WindowSpec{Name: name, LoginShell: true})
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	fmt.Fprintln(out, win.ID)
	return true, 0
}

func nativeCLIListWindows(cli *sessionipc.Client, args []string, out, errOut io.Writer) (bool, int) {
	if len(args) < 1 {
		fmt.Fprintln(errOut, "usage: roami session lw <session>")
		return true, 2
	}
	sessionID := args[0]
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	wins, err := cli.ListWindows(ctx, sessionID)
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	tw := tabwriter.NewWriter(out, 0, 2, 2, ' ', 0)
	fmt.Fprintln(tw, "WINDOW\tNAME\tACTIVE_PANE\tPANES")
	for _, w := range wins {
		var panes []string
		if w.Layout != nil {
			panes = w.Layout.PaneIDs()
		}
		fmt.Fprintf(tw, "%s\t%s\t%s\t%s\n", w.ID, w.Name, w.ActivePaneID, strings.Join(panes, ","))
	}
	_ = tw.Flush()
	return true, 0
}

func nativeCLICloseWindow(cli *sessionipc.Client, args []string, _ io.Writer, errOut io.Writer) (bool, int) {
	if len(args) < 2 {
		fmt.Fprintln(errOut, "usage: roami session kw <session> <windowId>")
		return true, 2
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	err := cli.CloseWindow(ctx, args[0], args[1])
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	return true, 0
}

func nativeCLICapture(cli *sessionipc.Client, args []string, out, errOut io.Writer) (bool, int) {
	var sessionID, paneID string
	includeHistory := false
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--pane", "-p":
			if i+1 < len(args) {
				i++
				paneID = args[i]
			}
		case "--history", "-S":
			includeHistory = true
		default:
			if !strings.HasPrefix(args[i], "-") && sessionID == "" {
				sessionID = args[i]
			}
		}
	}
	if sessionID == "" {
		fmt.Fprintln(errOut, "usage: roami session capture <session> [--pane ID]")
		return true, 2
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	res, err := cli.Capture(ctx, sessionbackend.Target{SessionID: sessionID, PaneID: paneID}, sessionbackend.CaptureOpts{
		IncludeHistory: includeHistory,
	})
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	fmt.Fprintln(out, res.Text)
	return true, 0
}

func nativeCLISend(cli *sessionipc.Client, args []string, _ io.Writer, errOut io.Writer) (bool, int) {
	if len(args) < 2 {
		fmt.Fprintln(errOut, "usage: roami session send <session> <text...>")
		return true, 2
	}
	sessionID := args[0]
	payload := strings.Join(args[1:], " ")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_, err := cli.Submit(ctx, sessionbackend.Target{SessionID: sessionID}, sessionbackend.SubmitReq{
		RequestID:      uuid.NewString(),
		Payload:        payload,
		SubmitEnter:    true,
		BracketedPaste: false,
	})
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	return true, 0
}

func nativeCLIRename(cli *sessionipc.Client, args []string, _ io.Writer, errOut io.Writer) (bool, int) {
	if len(args) < 2 {
		fmt.Fprintln(errOut, "usage: roami session rename <session> <label>")
		return true, 2
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	err := cli.Rename(ctx, args[0], strings.Join(args[1:], " "))
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	return true, 0
}

func nativeCLIKill(cli *sessionipc.Client, args []string, _ io.Writer, errOut io.Writer) (bool, int) {
	if len(args) < 1 {
		fmt.Fprintln(errOut, "usage: roami session kill <session>")
		return true, 2
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	err := cli.Close(ctx, args[0])
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	return true, 0
}
