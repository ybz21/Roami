package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"syscall"

	"github.com/ybz21/Roami/internal/agentexecution"
	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func runAgentExecution(args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		fmt.Println("roami agent execution launch --file SPEC.json\nroami agent execution status|cancel --key LAUNCH_KEY\nroami agent execution hold --file - (native workspace lease protocol)\nroami agent execution hook-config --executor codex\nroami agent execution event --executor codex --file -\n  launch creates a one-shot coding session, or continues a sessionId with verified lifecycle callbacks; projectId prepares a fresh project worktree; projectId + workspaceId reuses a registered workspace without fetch/reset")
		return 0
	}
	sub := args[0]
	if sub != "launch" && sub != "status" && sub != "cancel" && sub != "run" && sub != "hold" && sub != "event" && sub != "hook-config" {
		fmt.Fprintln(os.Stderr, "unknown execution command")
		return 2
	}
	fs := flag.NewFlagSet("agent execution "+sub, flag.ContinueOnError)
	file := fs.String("file", "", "execution spec, or - for stdin")
	key := fs.String("key", "", "stable launch key")
	executor := fs.String("executor", "", "lifecycle callback provider")
	notification := fs.String("notification", "", "provider completion JSON argument")
	if err := fs.Parse(args[1:]); err != nil {
		return 2
	}
	if fs.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "unexpected positional arguments")
		return 2
	}
	fail := func(err error) int { fmt.Fprintln(os.Stderr, err); return 1 }
	release, err := instanceLease()
	if err != nil {
		return fail(err)
	}
	defer release()
	exe, err := os.Executable()
	if err != nil {
		return fail(err)
	}
	service := agentexecution.Service{Runtime: runtime.New(), Executable: exe}
	var status agentexecution.Status
	switch sub {
	case "hook-config":
		config, err := agentexecution.HookConfiguration(exe, *executor)
		if err != nil {
			return fail(err)
		}
		if err = json.NewEncoder(os.Stdout).Encode(config); err != nil {
			return fail(err)
		}
		return 0
	case "event":
		if (*file == "") == (*notification == "") {
			return fail(fmt.Errorf("event requires either --file or --notification"))
		}
		content, err := agentInput(*file, *notification)
		if err != nil {
			return fail(err)
		}
		event, err := agentexecution.DecodeSessionEvent(content)
		if err != nil {
			return fail(err)
		}
		if err = service.ObserveSessionEvent(context.Background(), *executor, os.Getenv("TMUX_PANE"), event); err != nil {
			if err.Error() == "SESSION_TASK_CANCEL_REQUESTED" {
				_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"hookSpecificOutput": map[string]string{"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "The Roami task was cancelled; finish without starting another tool."}})
				return 0
			}
			return fail(err)
		}
		// Hooks consume this output; never inject receipt JSON as developer context.
		fmt.Println("{}")
		return 0
	case "hold":
		if *file != "-" {
			return fail(fmt.Errorf("hold requires --file - and newline-delimited JSON"))
		}
		decoder := json.NewDecoder(io.LimitReader(os.Stdin, 200000))
		var spec agentexecution.Spec
		if err = decoder.Decode(&spec); err != nil {
			return fail(err)
		}
		runCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM, syscall.SIGHUP)
		defer stop()
		if err = service.HoldNative(runCtx, spec, decoder, os.Stdout); err != nil {
			return fail(err)
		}
		return 0
	case "launch":
		if *file == "" {
			return fail(fmt.Errorf("--file is required"))
		}
		content, err := agentInput(*file, "")
		if err != nil {
			return fail(err)
		}
		var spec agentexecution.Spec
		if err = json.Unmarshal(content, &spec); err != nil {
			return fail(err)
		}
		status, err = service.Launch(context.Background(), spec)
		if err != nil {
			return fail(err)
		}
	case "status":
		status, err = service.Status(*key)
	case "cancel":
		status, err = service.Cancel(*key)
	case "run":
		runCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM, syscall.SIGHUP)
		defer stop()
		returnCode := service.Run(runCtx, *key, os.Stdout, os.Stderr)
		if returnCode != nil {
			return fail(returnCode)
		}
		return 0
	}
	if err != nil {
		return fail(err)
	}
	if err = json.NewEncoder(os.Stdout).Encode(status); err != nil {
		return fail(err)
	}
	return 0
}
