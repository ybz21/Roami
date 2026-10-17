package main

import (
	"flag"
	"fmt"
	"net/url"
	"os"

	"github.com/ybz21/Roami/internal/agentruntime"
)

func runAgentControl(args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		fmt.Println("roami agent control ls --task ID\nroami agent control show|pause|resume --resource ID\nPause returns takeoverReady only after actual input stop and lease release; poll show while pausing.")
		return 0
	}
	sub := args[0]
	if sub != "ls" && sub != "show" && sub != "pause" && sub != "resume" {
		fmt.Fprintln(os.Stderr, "unknown agent control command")
		return 2
	}
	flags := flag.NewFlagSet("agent control "+sub, flag.ContinueOnError)
	task := flags.String("task", "", "root task ID")
	resource := flags.String("resource", "", "resource ID")
	_ = flags.Bool("json", true, "JSON output")
	if err := flags.Parse(args[1:]); err != nil || flags.NArg() != 0 {
		return 2
	}
	method, path := "GET", ""
	if sub == "ls" {
		if *task == "" {
			fmt.Fprintln(os.Stderr, "--task is required")
			return 2
		}
		path = "/v1/tasks/" + url.PathEscape(*task) + "/resources"
	} else {
		if *resource == "" {
			fmt.Fprintln(os.Stderr, "--resource is required")
			return 2
		}
		path = "/v1/resources/" + url.PathEscape(*resource)
		if sub != "show" {
			method, path = "POST", path+"/"+sub
		}
	}
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	raw, err := agentRequest(paths.Socket, method, path, nil)
	if len(raw) > 0 {
		fmt.Println(string(raw))
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}
