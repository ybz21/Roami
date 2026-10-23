package main

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/agentruntime"
	metadb "github.com/ybz21/Roami/internal/storage"
)

func runAgent(args []string) int {
	if len(args) == 1 && args[0] == "installed-status" {
		if err := agentInstalledStatus(); err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		return 0
	}
	if len(args) > 0 && args[0] == "install-probe" {
		return runAgentInstallProbe(args[1:])
	}
	if len(args) > 0 && (args[0] == "prepare-upgrade" || args[0] == "resume-upgrade") {
		return runAgentUpgrade(args)
	}
	if len(args) > 0 && args[0] == "install-bundle" {
		return runAgentBundle(args[1:])
	}
	if len(args) > 0 && args[0] == "capability" {
		return runAgentCapability(args[1:])
	}
	if len(args) > 0 && args[0] == "reminder" {
		return runAgentReminder(args[1:])
	}
	if len(args) > 0 && args[0] == "notification-preferences" {
		return runAgentNotificationPreferences(args[1:])
	}
	if len(args) > 0 && args[0] == "control" {
		return runAgentControl(args[1:])
	}
	if len(args) > 0 && args[0] == "execution" {
		return runAgentExecution(args[1:])
	}
	if len(args) > 0 && args[0] == "trace" {
		return runAgentTrace(args[1:])
	}
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		fmt.Println("roami agent setup|init|serve|status|installed-status|install-bundle|install-probe|prepare-upgrade|resume-upgrade|conversations|new|send|history|report|reply|notify|steer|steering|task|memory|target|control|reminder|notification-preferences|execution|capability|trace [flags]\n  --runtime-dir PATH  Python project (setup/init/serve)\n  send --conversation ID --text TEXT [--key IDEMPOTENCY_KEY]\n  report --task ID --run ID --revision N --file RESULT.json\n  reply --dispatch ID --file RESULT.json (session executor report to originating Main)\n  notify --conversation ID --source SOURCE --key KEY --file MESSAGE.txt\n  steer --task ID --revision N --key KEY --text TEXT\n  steering --task ID --operation ID\n  control ls --task ID; control show|pause|resume --resource ID\n  trace --turn ID|--task ID [--format json|chrome]\n  serve uses the private Unix socket; public HTTP/SSE goes through roami server")
		return 0
	}
	sub := args[0]
	fs := flag.NewFlagSet("agent "+sub, flag.ContinueOnError)
	runtimeDir := fs.String("runtime-dir", "", "Python runtime project")
	conversation := fs.String("conversation", "", "conversation ID")
	text := fs.String("text", "", "message text")
	file := fs.String("file", "", "message/result file, or - for stdin")
	key := fs.String("key", "", "idempotency key")
	task := fs.String("task", "", "task ID")
	dispatch := fs.String("dispatch", "", "session assignment ID supplied with the task")
	run := fs.String("run", "", "run ID")
	operation := fs.String("operation", "", "steering operation ID")
	revision := fs.Int("revision", 1, "task revision")
	source := fs.String("source", "local-cli", "proactive source")
	title := fs.String("title", "New conversation", "conversation title")
	_ = fs.Bool("json", true, "JSON output")
	if err := fs.Parse(args[1:]); err != nil {
		return 2
	}
	if fs.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "unexpected positional arguments")
		return 2
	}
	fail := func(err error) int { fmt.Fprintln(os.Stderr, err); return 1 }
	if sub == "setup" || sub == "init" || sub == "serve" {
		dir, err := agentRuntimeDir(*runtimeDir)
		if err != nil {
			return fail(err)
		}
		if sub == "setup" {
			if _, e := os.Stat(filepath.Join(dir, "requirements.txt")); e == nil {
				if e = setupBundledAgent(dir); e != nil {
					return fail(e)
				}
				return 0
			}
			cmd := exec.Command("uv", "sync", "--frozen", "--project", dir)
			cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
			if err = cmd.Run(); err != nil {
				return fail(err)
			}
			return 0
		}
		if err = initializeAgent(dir); err != nil {
			return fail(err)
		}
		if sub == "init" {
			fmt.Println(`{"ok":true}`)
			return 0
		}
		p, err := agentruntime.Resolve("", "")
		if err != nil {
			return fail(err)
		}
		if err = agentPython(dir, p, false); err != nil {
			return fail(err)
		}
		return 0
	}
	if sub != "status" && sub != "conversations" && sub != "new" && sub != "send" && sub != "history" && sub != "report" && sub != "reply" && sub != "notify" && sub != "steer" && sub != "steering" {
		fmt.Fprintf(os.Stderr, "unknown agent command %q\n", sub)
		return 2
	}
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		return fail(err)
	}
	var body any
	method, path := "GET", "/v1/status"
	switch sub {
	case "conversations":
		path = "/v1/conversations"
	case "new":
		request := map[string]string{"title": *title}
		if *key != "" {
			request["requestKey"] = *key
		}
		method, path, body = "POST", "/v1/conversations", request
	case "history":
		if *conversation == "" {
			return fail(fmt.Errorf("--conversation is required"))
		}
		path = "/v1/conversations/" + url.PathEscape(*conversation) + "/messages"
	case "send", "notify":
		if *conversation == "" {
			return fail(fmt.Errorf("--conversation is required"))
		}
		content, err := agentInput(*file, *text)
		if err != nil {
			return fail(err)
		}
		if *key == "" {
			if sub == "notify" {
				return fail(fmt.Errorf("notify requires --key for durable deduplication"))
			}
			*key = fmt.Sprintf("cli-%d", time.Now().UnixNano())
		}
		method = "POST"
		if sub == "send" {
			path = "/v1/conversations/" + url.PathEscape(*conversation) + "/messages"
			body = map[string]string{"requestKey": *key, "text": string(content)}
		} else {
			path = "/internal/notify"
			body = map[string]string{"conversationId": *conversation, "text": string(content), "source": *source, "dedupeKey": *key}
		}
	case "steer":
		if *task == "" || *key == "" || *revision < 1 {
			return fail(fmt.Errorf("steer requires --task, --revision and --key"))
		}
		revisionSet := false
		fs.Visit(func(f *flag.Flag) {
			if f.Name == "revision" {
				revisionSet = true
			}
		})
		if !revisionSet {
			return fail(fmt.Errorf("steer requires explicit --revision"))
		}
		content, err := agentInput(*file, *text)
		if err != nil {
			return fail(err)
		}
		method, path, body = "POST", "/v1/tasks/"+url.PathEscape(*task)+"/steer", map[string]any{"requestKey": *key, "revision": *revision, "text": string(content)}
	case "steering":
		if *task == "" || *operation == "" {
			return fail(fmt.Errorf("steering requires --task and --operation"))
		}
		path = "/v1/tasks/" + url.PathEscape(*task) + "/steering/" + url.PathEscape(*operation)
	case "report":
		if *task == "" || *run == "" || *file == "" {
			return fail(fmt.Errorf("report requires --task, --run and --file"))
		}
		content, err := agentInput(*file, "")
		if err != nil {
			return fail(err)
		}
		var result map[string]any
		if err = json.Unmarshal(content, &result); err != nil {
			return fail(err)
		}
		method, path, body = "POST", "/internal/report", map[string]any{"taskId": *task, "runId": *run, "revision": *revision, "result": result}
	case "reply":
		if *dispatch == "" || *file == "" || *conversation != "" || *text != "" || *task != "" || *run != "" || *key != "" {
			return fail(fmt.Errorf("reply requires --dispatch and --file; routing and idempotency come from the assignment and result JSON"))
		}
		content, err := agentInput(*file, "")
		if err != nil {
			return fail(err)
		}
		var result map[string]any
		if err = json.Unmarshal(content, &result); err != nil {
			return fail(err)
		}
		method, path, body = "POST", "/internal/session-dispatches/"+url.PathEscape(*dispatch)+"/reply", result
	}
	raw, err := agentRequest(paths.Socket, method, path, body)
	if len(raw) > 0 {
		fmt.Println(string(raw))
	}
	if err != nil {
		return fail(err)
	}
	return 0
}

func agentRuntimeDir(explicit string) (string, error) {
	if explicit == "" {
		explicit = os.Getenv("ROAMI_AGENT_RUNTIME")
	}
	if explicit != "" {
		p, e := filepath.Abs(explicit)
		if e != nil {
			return "", e
		}
		if _, e = os.Stat(filepath.Join(p, "pyproject.toml")); e != nil {
			return "", e
		}
		return p, nil
	}
	exe, _ := os.Executable()
	exe, _ = filepath.EvalSymlinks(exe)
	for _, dir := range []string{filepath.Join(filepath.Dir(exe), "..", "runtime"), filepath.Join(filepath.Dir(exe), "agent-runtime"), "agent-runtime"} {
		if _, e := os.Stat(filepath.Join(dir, "pyproject.toml")); e == nil {
			return filepath.Abs(dir)
		}
	}
	return "", fmt.Errorf("AGENT_RUNTIME_NOT_INSTALLED: pass --runtime-dir or set ROAMI_AGENT_RUNTIME")
}

func initializeAgent(dir string) error {
	p, err := metadb.ResolvePaths("", "")
	if err != nil {
		return err
	}
	if _, err = metadb.Open(p.Home, metadb.Options{HomeDir: p.Home, DataDir: p.Data}); err != nil {
		return err
	}
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		return err
	}
	release, err := p.Lock("storage", false)
	if err != nil {
		return err
	}
	defer release()
	catalog, err := p.Catalog()
	if err != nil {
		return err
	}
	ready := false
	for _, entry := range catalog.Databases {
		if entry.ID == "agent-runtime" {
			ready = entry.State == "ready"
			break
		}
	}
	if !ready {
		if err = p.Register(paths.Descriptor("pending")); err != nil {
			return err
		}
	}
	if err = agentPython(dir, paths, true); err != nil {
		return err
	}
	return p.Register(paths.Descriptor("ready"))
}

func agentPythonCommand(dir string, p agentruntime.Paths, initialize bool) (*exec.Cmd, error) {
	python := os.Getenv("ROAMI_AGENT_PYTHON")
	if python == "" {
		python = filepath.Join(dir, ".venv", "bin", "python")
	}
	if _, err := exec.LookPath(python); err != nil {
		return nil, fmt.Errorf("AGENT_DEPENDENCIES_MISSING: run roami agent setup --runtime-dir %q", dir)
	}
	args := []string{"-I", "-m", "roami_agent.app", "--data-root", p.Storage.Data, "--database", p.Database, "--config", p.Config}
	if initialize {
		args = append(args, "--initialize")
	} else {
		args = append(args, "--socket", p.Socket)
	}
	cmd := exec.Command(python, args...)
	cmd.Env = agentEnvironment()
	if binary, err := os.Executable(); err == nil {
		cmd.Env = append(cmd.Env, "ROAMI_AGENT_CLI="+binary, "ROAMI_AGENT_VERSION="+version)
	}
	cmd.Dir = dir
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	return cmd, nil
}

func agentPython(dir string, p agentruntime.Paths, initialize bool) error {
	cmd, err := agentPythonCommand(dir, p, initialize)
	if err != nil {
		return err
	}
	return cmd.Run()
}

func agentInput(file, text string) ([]byte, error) {
	var reader io.Reader
	if file == "-" {
		reader = os.Stdin
	} else if file != "" {
		f, e := os.Open(file)
		if e != nil {
			return nil, e
		}
		defer f.Close()
		reader = f
	} else {
		reader = bytes.NewBufferString(text)
	}
	b, e := io.ReadAll(io.LimitReader(reader, 100001))
	if e != nil {
		return nil, e
	}
	if len(b) > 100000 {
		return nil, fmt.Errorf("AGENT_INPUT_TOO_LARGE")
	}
	return b, nil
}

func agentRequest(socket, method, path string, body any) ([]byte, error) {
	var data []byte
	if body != nil {
		var err error
		data, err = json.Marshal(body)
		if err != nil {
			return nil, err
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	if method == "POST" && strings.HasPrefix(path, "/v1/tool-directory/") && strings.HasSuffix(path, "/call") {
		cancel()
		ctx, cancel = context.WithTimeout(context.Background(), 100*time.Second)
	}
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, method, "http://roami-agent"+path, bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Roami-Owner", "local")
	transport := agentruntime.Transport(socket)
	if method == "POST" && strings.HasPrefix(path, "/v1/tool-directory/") && strings.HasSuffix(path, "/call") {
		transport.ResponseHeaderTimeout = 100 * time.Second
	}
	defer transport.CloseIdleConnections()
	response, err := (&http.Client{Transport: transport}).Do(req)
	if err != nil {
		return nil, fmt.Errorf("AGENT_RUNTIME_UNAVAILABLE: %w", err)
	}
	defer response.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(response.Body, 4<<20))
	if err != nil {
		return nil, err
	}
	if response.StatusCode >= 400 {
		return raw, fmt.Errorf("agent HTTP %d", response.StatusCode)
	}
	return raw, nil
}
