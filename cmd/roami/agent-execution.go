package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/ybz21/Roami/internal/agentexecution"
	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func runAgentExecution(args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		fmt.Println("roami agent execution launch --file SPEC.json\nroami agent execution status|cancel --key LAUNCH_KEY\n  launch creates a new one-shot coding session; projectId prepares a fresh project worktree through Go")
		return 0
	}
	sub := args[0]
	if sub != "launch" && sub != "status" && sub != "cancel" && sub != "run" {
		fmt.Fprintln(os.Stderr, "unknown execution command")
		return 2
	}
	fs := flag.NewFlagSet("agent execution "+sub, flag.ContinueOnError)
	file := fs.String("file", "", "execution spec, or - for stdin")
	key := fs.String("key", "", "stable launch key")
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
