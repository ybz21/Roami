package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"text/tabwriter"
	"time"

	"github.com/google/uuid"
	app "github.com/ybz21/Roami/internal/cli"
	"github.com/ybz21/Roami/internal/cli/nativeattach"
	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessionipc"
	metadb "github.com/ybz21/Roami/internal/storage"
	ui "github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/ttyraw"
)

// maybeRunNativeSessionCLI integrates native roami-sessiond sessions into `roami session`:
//   - `new`: routes to native when `--backend native`, `ROAMI_NATIVE_TERMINAL=1`, or on Windows.
//   - `ls`: merges live native sessions alongside legacy tmux sessions (plain and --json).
//   - target commands (`a/attach/sp/kp/nw/lw/kw/capture/send/rename/kill`): auto-route by ID
//     or unique friendly label to an already-running native host without needing any env var.
func maybeRunNativeSessionCLI(args []string) (bool, int) {
	if len(args) == 0 {
		return false, 0
	}
	cmd, rest := args[0], args[1:]
	switch cmd {
	case "new", "ls", "a", "attach", "window", "pane", "sp", "split", "kp", "nw", "lw", "kw", "capture", "send", "rename", "kill":
	default:
		return false, 0
	}
	if isHelpInvocation(cmd, rest) {
		return false, 0
	}
	return dispatchNativeSessionCLI(cmd, rest, os.Stdin, os.Stdout, os.Stderr)
}

func isHelpInvocation(cmd string, rest []string) bool {
	if len(rest) == 0 {
		return cmd == "window" || cmd == "pane"
	}
	// Preserve literal payloads for `send <session> --help` and legacy `sp -h` (horizontal split).
	if cmd == "send" && len(rest) >= 2 {
		return false
	}
	if (cmd == "sp" || cmd == "split") && len(rest) == 1 && rest[0] == "-h" {
		return false
	}
	if rest[0] == "--help" || rest[0] == "-h" || rest[0] == "help" {
		return true
	}
	last := rest[len(rest)-1]
	if last == "--help" || (last == "-h" && cmd != "sp" && cmd != "split") {
		return true
	}
	return false
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
	case "window":
		return nativeCLIWindow(cli, rest, in, out, errOut)
	case "pane":
		return nativeCLIPane(cli, rest, out, errOut)
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

// resolveNativeSessionID resolves a session query by exact ID first, then unique friendly label.
// Returns ErrSessionNotFound when no native session matches so callers can fall back to tmux.
func resolveNativeSessionID(ctx context.Context, cli *sessionipc.Client, query string) (string, error) {
	if query == "" {
		return "", sessionbackend.ErrSessionNotFound
	}
	if _, err := cli.Observe(ctx, query); err == nil {
		return query, nil
	} else if !errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return "", err
	}
	list, err := cli.List(ctx)
	if err != nil {
		return "", err
	}
	var matches []string
	for _, s := range list {
		if s.ID == query {
			return s.ID, nil
		}
		if s.Label == query {
			matches = append(matches, s.ID)
		}
	}
	switch len(matches) {
	case 0:
		return "", sessionbackend.ErrSessionNotFound
	case 1:
		return matches[0], nil
	default:
		return "", fmt.Errorf("多个原生会话匹配 %q（%s），请改用会话 ID", query, strings.Join(matches, ", "))
	}
}

func parseTermSize(raw string) (cols, rows uint16, err error) {
	wStr, hStr, ok := strings.Cut(strings.ToLower(strings.TrimSpace(raw)), "x")
	if !ok {
		return 0, 0, fmt.Errorf("invalid --size %q (expected WIDTHxHEIGHT)", raw)
	}
	w, err1 := strconv.Atoi(wStr)
	h, err2 := strconv.Atoi(hStr)
	if err1 != nil || err2 != nil || w < 20 || w > 1000 || h < 6 || h > 500 {
		return 0, 0, fmt.Errorf("invalid --size %q (expected 20..1000 x 6..500)", raw)
	}
	return uint16(w), uint16(h), nil
}

func nativeCLICreate(cli *sessionipc.Client, args []string, in io.Reader, out, errOut io.Writer) int {
	spec := sessionbackend.CreateSpec{LoginShell: true}
	detach := false
	asJSON := false
	reuse := true
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
		case "--size":
			if i+1 >= len(args) {
				fmt.Fprintln(errOut, "missing value for --size")
				return 2
			}
			i++
			cols, rows, err := parseTermSize(args[i])
			if err != nil {
				fmt.Fprintln(errOut, err)
				return 2
			}
			spec.Cols, spec.Rows = cols, rows
		case "--label":
			if i+1 >= len(args) {
				fmt.Fprintln(errOut, "missing value for --label")
				return 2
			}
			i++
			spec.Label = args[i]
		case "--no-reuse":
			reuse = false
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
	defer cancel()

	// Match `roami session new`: reuse an alive session with the same name/label unless --no-reuse.
	var ref sessionbackend.SessionRef
	reused := false
	if reuse && spec.SessionID != "" {
		if existingID, rerr := resolveNativeSessionID(ctx, cli, spec.SessionID); rerr == nil {
			if st, oerr := cli.Observe(ctx, existingID); oerr == nil && st.Status == sessionbackend.StatusAlive {
				ref = sessionbackend.SessionRef{
					SessionID:      st.SessionID,
					Label:          st.Label,
					Backend:        sessionbackend.BackendNative,
					HostInstanceID: st.HostInstanceID,
					WindowID:       st.ActiveWindowID,
					PaneID:         st.ActivePaneID,
					Reused:         true,
				}
				reused = true
			}
		}
	}
	if !reused {
		var err error
		ref, err = cli.Create(ctx, spec)
		if err != nil {
			fmt.Fprintln(errOut, err)
			return 1
		}
	}

	if asJSON {
		payload := map[string]any{
			"session": ref.SessionID,
			"label":   ref.Label,
			"backend": ref.Backend,
			"window":  ref.WindowID,
			"pane":    ref.PaneID,
		}
		if reused {
			payload["reused"] = ref.SessionID
		}
		_ = json.NewEncoder(out).Encode(payload)
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
			Cols:      spec.Cols,
			Rows:      spec.Rows,
		}); err != nil {
			fmt.Fprintln(errOut, err)
			return 1
		}
		return 0
	}
	fmt.Fprintln(out, ref.SessionID)
	return 0
}

func nativeSummaryAsSessionJSON(s sessionbackend.SessionSummary) map[string]any {
	label := s.Label
	if label == "" {
		label = s.ID
	}
	state := "live"
	if s.Status == sessionbackend.StatusExited {
		state = "exited"
	}
	return map[string]any{
		"name":           s.ID,
		"id":             s.ID,
		"label":          label,
		"backend":        string(s.Backend),
		"hostInstanceId": s.HostInstanceID,
		"windows":        s.Windows,
		"created":        strconv.FormatInt(s.CreatedAt.Unix(), 10),
		"last_activity":  strconv.FormatInt(s.LastActivityAt.Unix(), 10),
		"attached":       s.Attached,
		"state":          state,
		"dir":            s.Dir,
	}
}

func formatNativeSessionLines(list []sessionbackend.SessionSummary, w io.Writer) {
	p := ui.P()
	for _, s := range list {
		ts := s.CreatedAt.Format("01-02 15:04")
		display := s.Label
		if display == "" {
			display = s.ID
		}
		label := ui.Bold(display)
		if s.ID != "" && s.ID != display {
			label += p.Dim + "(" + s.ID + ")" + p.Reset
		}
		att := ui.Dim("[空闲]")
		if s.Attached > 0 {
			att = p.Green + "[已连接]" + p.Reset
		}
		tag := p.Dim + "[native]" + p.Reset
		fmt.Fprintf(w, "   %s %s  %s%d 个窗口  %s%s  %s  %s\n",
			ui.IconSession, label, p.Dim, s.Windows, ts, p.Reset, tag, att)
	}
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
		if nativeOnly {
			if list == nil {
				list = []sessionbackend.SessionSummary{}
			}
			enc := json.NewEncoder(out)
			enc.SetIndent("", "  ")
			_ = enc.Encode(list)
			return true, 0
		}
		// Merge tmux JSON rows with native rows so `roami session ls --json` never hides tmux sessions.
		var merged []map[string]any
		var tmuxBuf bytes.Buffer
		if app.New().WithOutput(&tmuxBuf).Run(append([]string{"ls"}, args...)) == nil {
			var tmuxRows []map[string]any
			if json.Unmarshal(bytes.TrimSpace(tmuxBuf.Bytes()), &tmuxRows) == nil {
				for _, r := range tmuxRows {
					if _, ok := r["backend"]; !ok {
						r["backend"] = string(sessionbackend.BackendTmux)
					}
					merged = append(merged, r)
				}
			}
		}
		for _, s := range list {
			merged = append(merged, nativeSummaryAsSessionJSON(s))
		}
		if merged == nil {
			merged = []map[string]any{}
		}
		enc := json.NewEncoder(out)
		enc.SetIndent("", "  ")
		_ = enc.Encode(merged)
		return true, 0
	}

	if nativeOnly {
		if len(list) == 0 {
			ui.Info(out, "没有原生会话")
			return true, 0
		}
		fmt.Fprintln(out)
		formatNativeSessionLines(list, out)
		fmt.Fprintf(out, "\n   %s共 %d 个原生会话%s\n\n", ui.P().Dim, len(list), ui.P().Reset)
		return true, 0
	}

	// Render legacy tmux sessions first, then append native rows in the same visual style.
	var tmuxBuf bytes.Buffer
	_ = app.New().WithOutput(&tmuxBuf).Run(append([]string{"ls"}, args...))
	tmuxOut := tmuxBuf.String()
	if len(list) == 0 {
		_, _ = io.WriteString(out, tmuxOut)
		return true, 0
	}
	if !strings.Contains(tmuxOut, "没有活跃会话") && strings.TrimSpace(tmuxOut) != "" {
		_, _ = io.WriteString(out, tmuxOut)
	} else {
		fmt.Fprintln(out)
	}
	formatNativeSessionLines(list, out)
	fmt.Fprintf(out, "\n   %s另有 %d 个原生会话（native）%s\n\n", ui.P().Dim, len(list), ui.P().Reset)
	return true, 0
}

// resolveNativeWindow resolves a window query by exact ID, exact Name, or 1-based index.
func resolveNativeWindow(wins []sessionbackend.Window, query string) (sessionbackend.Window, error) {
	if query == "" {
		return sessionbackend.Window{}, sessionbackend.ErrWindowNotFound
	}
	for _, w := range wins {
		if w.ID == query {
			return w, nil
		}
	}
	var nameMatches []sessionbackend.Window
	for _, w := range wins {
		if w.Name == query {
			nameMatches = append(nameMatches, w)
		}
	}
	if len(nameMatches) == 1 {
		return nameMatches[0], nil
	}
	if len(nameMatches) > 1 {
		ids := make([]string, len(nameMatches))
		for i, w := range nameMatches {
			ids[i] = w.ID
		}
		return sessionbackend.Window{}, fmt.Errorf("多个窗口同名 %q（%s），请改用窗口 ID 或序号", query, strings.Join(ids, ", "))
	}
	if idx, err := strconv.Atoi(query); err == nil && idx >= 1 && idx <= len(wins) {
		return wins[idx-1], nil
	}
	return sessionbackend.Window{}, fmt.Errorf("找不到窗口 %q（共 %d 个窗口，可用 roami session window ls 查看）", query, len(wins))
}

func nativeCLIAttach(cli *sessionipc.Client, args []string, in io.Reader, out, errOut io.Writer) (bool, int) {
	var sessionQuery, windowQuery, paneID string
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--pane", "-p":
			if i+1 >= len(args) {
				fmt.Fprintln(errOut, "missing value for --pane")
				return true, 2
			}
			i++
			paneID = args[i]
		case "--window", "-w":
			if i+1 >= len(args) {
				fmt.Fprintln(errOut, "missing value for --window")
				return true, 2
			}
			i++
			windowQuery = args[i]
		default:
			if !strings.HasPrefix(args[i], "-") && sessionQuery == "" {
				sessionQuery = args[i]
			}
		}
	}
	// Support tmux-style `SESSION:WINDOW` shorthand when `--window` is not explicitly given.
	if sessionQuery != "" && windowQuery == "" {
		if sPart, wPart, ok := strings.Cut(sessionQuery, ":"); ok && sPart != "" && wPart != "" {
			sessionQuery, windowQuery = sPart, wPart
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	var sessionID string
	if sessionQuery == "" {
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
		if len(alive) == 0 {
			return false, 0
		}
		if len(alive) == 1 {
			sessionID = alive[0].ID
		} else if isReaderTTY(in) {
			var b strings.Builder
			fmt.Fprintf(&b, "\n   %s:\n\n", ui.Bold("选择要进入的原生会话"))
			for i, s := range alive {
				disp := s.ID
				if s.Label != "" && s.Label != s.ID {
					disp = fmt.Sprintf("%s (%s)", s.Label, s.ID)
				}
				fmt.Fprintf(&b, "   %d) %s  [native]\n", i+1, disp)
			}
			choice, ok := ui.ReadLine(b.String() + "\n   输入编号或名称: ")
			if !ok {
				return true, 1
			}
			if n, err := strconv.Atoi(choice); err == nil && n >= 1 && n <= len(alive) {
				sessionID = alive[n-1].ID
			} else {
				rCtx, rCancel := context.WithTimeout(context.Background(), 5*time.Second)
				id, rerr := resolveNativeSessionID(rCtx, cli, choice)
				rCancel()
				if rerr != nil {
					fmt.Fprintln(errOut, rerr)
					return true, 1
				}
				sessionID = id
			}
		} else {
			fmt.Fprintln(errOut, "多个原生会话活跃，请指定名称或 ID：")
			for _, s := range alive {
				fmt.Fprintf(errOut, "  %s\n", s.ID)
			}
			return true, 2
		}
	} else {
		id, err := resolveNativeSessionID(ctx, cli, sessionQuery)
		cancel()
		if errors.Is(err, sessionbackend.ErrSessionNotFound) {
			return false, 0
		}
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		sessionID = id
	}

	var windowID string
	if windowQuery != "" {
		wCtx, wCancel := context.WithTimeout(context.Background(), 5*time.Second)
		wins, err := cli.ListWindows(wCtx, sessionID)
		if err != nil {
			wCancel()
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		win, err := resolveNativeWindow(wins, windowQuery)
		if err != nil {
			wCancel()
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		if err := cli.SelectWindow(wCtx, sessionID, win.ID); err != nil {
			wCancel()
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		wCancel()
		windowID = win.ID
		if paneID == "" {
			paneID = win.ActivePaneID
		}
	}

	if err := nativeattach.Attach(context.Background(), cli, cli, nativeattach.AttachOptions{
		SessionID: sessionID,
		WindowID:  windowID,
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

func nativeCLIWindow(cli *sessionipc.Client, args []string, in io.Reader, out, errOut io.Writer) (bool, int) {
	if len(args) == 0 {
		return false, 0
	}
	sub, rest := args[0], args[1:]
	switch sub {
	case "new":
		var sessionQuery, name, dir string
		attachAfter := false
		for i := 0; i < len(rest); i++ {
			switch rest[i] {
			case "-c", "--dir":
				if i+1 >= len(rest) {
					fmt.Fprintln(errOut, "missing value for --dir")
					return true, 2
				}
				i++
				dir = rest[i]
			case "-a", "--attach":
				attachAfter = true
			default:
				if strings.HasPrefix(rest[i], "-") {
					fmt.Fprintf(errOut, "unknown flag %q\n", rest[i])
					return true, 2
				}
				if sessionQuery == "" {
					sessionQuery = rest[i]
				} else if name == "" {
					name = rest[i]
				}
			}
		}
		if sessionQuery == "" {
			return false, 0
		}
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		sessionID, err := resolveNativeSessionID(ctx, cli, sessionQuery)
		if errors.Is(err, sessionbackend.ErrSessionNotFound) {
			cancel()
			return false, 0
		}
		if err != nil {
			cancel()
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		win, err := cli.NewWindow(ctx, sessionID, sessionbackend.WindowSpec{Name: name, Dir: dir, LoginShell: true})
		cancel()
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		if attachAfter && isReaderTTY(in) {
			if err := nativeattach.Attach(context.Background(), cli, cli, nativeattach.AttachOptions{
				SessionID: sessionID,
				WindowID:  win.ID,
				PaneID:    win.ActivePaneID,
				In:        in,
				Out:       out,
				RawTTY:    true,
			}); err != nil {
				fmt.Fprintln(errOut, err)
				return true, 1
			}
			return true, 0
		}
		fmt.Fprintln(out, win.ID)
		return true, 0

	case "ls", "list":
		return nativeCLIListWindows(cli, rest, out, errOut)

	case "select", "switch":
		if len(rest) < 2 {
			return false, 0
		}
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		sessionID, err := resolveNativeSessionID(ctx, cli, rest[0])
		if errors.Is(err, sessionbackend.ErrSessionNotFound) {
			return false, 0
		}
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		wins, err := cli.ListWindows(ctx, sessionID)
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		win, err := resolveNativeWindow(wins, rest[1])
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		if err := cli.SelectWindow(ctx, sessionID, win.ID); err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		ui.Ok(out, "已切换窗口 %s (%s)", ui.Bold(win.Name), win.ID)
		return true, 0

	case "kill", "rm", "close":
		if len(rest) < 1 {
			return false, 0
		}
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		sessionID, err := resolveNativeSessionID(ctx, cli, rest[0])
		if errors.Is(err, sessionbackend.ErrSessionNotFound) {
			return false, 0
		}
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		var targetWinID string
		if len(rest) >= 2 {
			wins, err := cli.ListWindows(ctx, sessionID)
			if err != nil {
				fmt.Fprintln(errOut, err)
				return true, 1
			}
			win, err := resolveNativeWindow(wins, rest[1])
			if err != nil {
				fmt.Fprintln(errOut, err)
				return true, 1
			}
			targetWinID = win.ID
		} else {
			st, err := cli.Observe(ctx, sessionID)
			if err != nil {
				fmt.Fprintln(errOut, err)
				return true, 1
			}
			targetWinID = st.ActiveWindowID
		}
		if err := cli.CloseWindow(ctx, sessionID, targetWinID); err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		ui.Ok(out, "窗口 %s 已关闭", ui.Bold(targetWinID))
		return true, 0

	default:
		return false, 0
	}
}

func nativeCLIPane(cli *sessionipc.Client, args []string, out, errOut io.Writer) (bool, int) {
	if len(args) == 0 {
		return false, 0
	}
	sub, rest := args[0], args[1:]
	switch sub {
	case "ls", "list":
		var sessionQuery, windowQuery string
		for i := 0; i < len(rest); i++ {
			switch rest[i] {
			case "-w", "--window":
				if i+1 < len(rest) {
					i++
					windowQuery = rest[i]
				}
			default:
				if !strings.HasPrefix(rest[i], "-") && sessionQuery == "" {
					sessionQuery = rest[i]
				}
			}
		}
		if sessionQuery == "" {
			return false, 0
		}
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		sessionID, err := resolveNativeSessionID(ctx, cli, sessionQuery)
		if errors.Is(err, sessionbackend.ErrSessionNotFound) {
			return false, 0
		}
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		st, err := cli.Observe(ctx, sessionID)
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		var filterWinID string
		if windowQuery != "" {
			win, err := resolveNativeWindow(st.Windows, windowQuery)
			if err != nil {
				fmt.Fprintln(errOut, err)
				return true, 1
			}
			filterWinID = win.ID
		}
		tw := tabwriter.NewWriter(out, 0, 2, 2, ' ', 0)
		fmt.Fprintln(tw, "PANE\tWINDOW\tSTATE")
		for i, w := range st.Windows {
			if filterWinID != "" && w.ID != filterWinID {
				continue
			}
			if w.Layout == nil {
				continue
			}
			for _, pid := range w.Layout.PaneIDs() {
				state := ""
				if pid == st.ActivePaneID {
					state = "[当前]"
				} else if pid == w.ActivePaneID {
					state = "[窗口活跃]"
				}
				fmt.Fprintf(tw, "%s\t%d:%s (%s)\t%s\n", pid, i+1, w.Name, w.ID, state)
			}
		}
		_ = tw.Flush()
		return true, 0

	case "split":
		dir := sessionbackend.SplitHorizontal
		var sessionQuery, windowQuery, paneID, cwd string
		for i := 0; i < len(rest); i++ {
			switch rest[i] {
			case "--right", "--horizontal", "-H":
				dir = sessionbackend.SplitHorizontal
			case "--down", "--vertical", "-V", "-v":
				dir = sessionbackend.SplitVertical
			case "--window", "-w":
				if i+1 >= len(rest) {
					fmt.Fprintln(errOut, "missing value for --window")
					return true, 2
				}
				i++
				windowQuery = rest[i]
			case "--pane", "-p":
				if i+1 >= len(rest) {
					fmt.Fprintln(errOut, "missing value for --pane")
					return true, 2
				}
				i++
				paneID = rest[i]
			case "-c", "--dir":
				if i+1 >= len(rest) {
					fmt.Fprintln(errOut, "missing value for --dir")
					return true, 2
				}
				i++
				cwd = rest[i]
			default:
				if strings.HasPrefix(rest[i], "-") {
					fmt.Fprintf(errOut, "unknown flag %q\n", rest[i])
					return true, 2
				}
				if sessionQuery == "" {
					sessionQuery = rest[i]
				}
			}
		}
		if sessionQuery == "" {
			return false, 0
		}
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		sessionID, err := resolveNativeSessionID(ctx, cli, sessionQuery)
		if errors.Is(err, sessionbackend.ErrSessionNotFound) {
			return false, 0
		}
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		st, err := cli.Observe(ctx, sessionID)
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		if paneID == "" && windowQuery != "" {
			win, err := resolveNativeWindow(st.Windows, windowQuery)
			if err != nil {
				fmt.Fprintln(errOut, err)
				return true, 1
			}
			paneID = win.ActivePaneID
		}
		if paneID == "" {
			paneID = st.ActivePaneID
		}
		_, newPaneID, err := cli.SplitPane(ctx, sessionID, paneID, sessionbackend.SplitSpec{
			Dir:        dir,
			Cwd:        cwd,
			LoginShell: true,
		})
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		fmt.Fprintln(out, newPaneID)
		return true, 0

	case "kill", "rm", "close":
		return nativeCLIClosePane(cli, rest, out, errOut)

	default:
		return false, 0
	}
}

func nativeCLISplit(cli *sessionipc.Client, args []string, out, errOut io.Writer) (bool, int) {
	dir := sessionbackend.SplitHorizontal
	var sessionQuery, paneID, cwd string
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
			if !strings.HasPrefix(args[i], "-") && sessionQuery == "" {
				sessionQuery = args[i]
			}
		}
	}
	if sessionQuery == "" {
		return false, 0
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	sessionID, err := resolveNativeSessionID(ctx, cli, sessionQuery)
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	st, err := cli.Observe(ctx, sessionID)
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
	var sessionQuery, paneID string
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--pane", "-p":
			if i+1 < len(args) {
				i++
				paneID = args[i]
			}
		default:
			if !strings.HasPrefix(args[i], "-") {
				if sessionQuery == "" {
					sessionQuery = args[i]
				} else if paneID == "" {
					paneID = args[i]
				}
			}
		}
	}
	if sessionQuery == "" {
		return false, 0
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	sessionID, err := resolveNativeSessionID(ctx, cli, sessionQuery)
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	st, err := cli.Observe(ctx, sessionID)
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
		return false, 0
	}
	var name string
	if len(args) > 1 {
		name = args[1]
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	sessionID, err := resolveNativeSessionID(ctx, cli, args[0])
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
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
		return false, 0
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	sessionID, err := resolveNativeSessionID(ctx, cli, args[0])
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	st, err := cli.Observe(ctx, sessionID)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	tw := tabwriter.NewWriter(out, 0, 2, 2, ' ', 0)
	fmt.Fprintln(tw, "INDEX\tWINDOW\tNAME\tACTIVE_PANE\tPANES\tSTATE")
	for i, w := range st.Windows {
		var panes []string
		if w.Layout != nil {
			panes = w.Layout.PaneIDs()
		}
		state := ""
		if w.ID == st.ActiveWindowID {
			state = "[活跃]"
		}
		fmt.Fprintf(tw, "%d\t%s\t%s\t%s\t%s\t%s\n", i+1, w.ID, w.Name, w.ActivePaneID, strings.Join(panes, ","), state)
	}
	_ = tw.Flush()
	return true, 0
}

func nativeCLICloseWindow(cli *sessionipc.Client, args []string, _ io.Writer, errOut io.Writer) (bool, int) {
	if len(args) < 2 {
		return false, 0
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	sessionID, err := resolveNativeSessionID(ctx, cli, args[0])
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	wins, err := cli.ListWindows(ctx, sessionID)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	win, err := resolveNativeWindow(wins, args[1])
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	if err := cli.CloseWindow(ctx, sessionID, win.ID); err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	return true, 0
}

func nativeCLICapture(cli *sessionipc.Client, args []string, out, errOut io.Writer) (bool, int) {
	var sessionQuery, windowQuery, paneID string
	includeHistory := false
	lines := 0
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--window", "-w":
			if i+1 < len(args) {
				i++
				windowQuery = args[i]
			}
		case "--pane", "-p":
			if i+1 < len(args) {
				i++
				paneID = args[i]
			}
		case "--lines", "-n":
			if i+1 < len(args) {
				i++
				if n, err := strconv.Atoi(args[i]); err == nil && n > 0 {
					lines = n
				}
			}
		case "--history", "-S":
			includeHistory = true
		default:
			if !strings.HasPrefix(args[i], "-") && sessionQuery == "" {
				sessionQuery = args[i]
			}
		}
	}
	if sessionQuery == "" {
		return false, 0
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	sessionID, err := resolveNativeSessionID(ctx, cli, sessionQuery)
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	var windowID string
	if windowQuery != "" && paneID == "" {
		wins, err := cli.ListWindows(ctx, sessionID)
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		win, err := resolveNativeWindow(wins, windowQuery)
		if err != nil {
			fmt.Fprintln(errOut, err)
			return true, 1
		}
		windowID = win.ID
		paneID = win.ActivePaneID
	}
	res, err := cli.Capture(ctx, sessionbackend.Target{SessionID: sessionID, WindowID: windowID, PaneID: paneID}, sessionbackend.CaptureOpts{
		Lines:          lines,
		IncludeHistory: includeHistory,
	})
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	fmt.Fprintln(out, res.Text)
	return true, 0
}

func nativeCLISend(cli *sessionipc.Client, args []string, _ io.Writer, errOut io.Writer) (bool, int) {
	if len(args) < 2 {
		return false, 0
	}
	payload := strings.Join(args[1:], " ")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	sessionID, err := resolveNativeSessionID(ctx, cli, args[0])
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	if _, err := cli.Submit(ctx, sessionbackend.Target{SessionID: sessionID}, sessionbackend.SubmitReq{
		RequestID:      uuid.NewString(),
		Payload:        payload,
		SubmitEnter:    true,
		BracketedPaste: false,
	}); err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	return true, 0
}

func nativeCLIRename(cli *sessionipc.Client, args []string, _ io.Writer, errOut io.Writer) (bool, int) {
	if len(args) < 2 {
		return false, 0
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	sessionID, err := resolveNativeSessionID(ctx, cli, args[0])
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	if err := cli.Rename(ctx, sessionID, strings.Join(args[1:], " ")); err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	return true, 0
}

func nativeCLIKill(cli *sessionipc.Client, args []string, _ io.Writer, errOut io.Writer) (bool, int) {
	if len(args) < 1 {
		return false, 0
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	sessionID, err := resolveNativeSessionID(ctx, cli, args[0])
	if errors.Is(err, sessionbackend.ErrSessionNotFound) {
		return false, 0
	}
	if err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	if err := cli.Close(ctx, sessionID); err != nil {
		fmt.Fprintln(errOut, err)
		return true, 1
	}
	return true, 0
}
