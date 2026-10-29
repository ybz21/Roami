package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/google/uuid"

	"github.com/ybz21/Roami/internal/agentruntime"
	"github.com/ybz21/Roami/internal/modelgateway"
)

func runAgentGateway(args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" {
		fmt.Println("roami agent gateway settings|usage|configure|reconcile [--file JSON] [--days 7] [--call ID]\n  configure replaces local pricing and daily limit; reconcile records a verified amount for an unknown call\n  requires roami server or roami agent serve")
		return 0
	}
	flags := flag.NewFlagSet("agent gateway", flag.ContinueOnError)
	file := flags.String("file", "", "configuration/reconciliation JSON file, or - for stdin")
	days := flags.Int("days", 7, "usage window, 1-90 days; 0 for lifetime")
	call := flags.String("call", "", "unknown call ID")
	if flags.Parse(args[1:]) != nil || flags.NArg() != 0 {
		return 2
	}
	method, path := "GET", "/v1/model-gateway/"+args[0]
	var body any
	switch args[0] {
	case "settings":
	case "usage":
		path += fmt.Sprintf("?days=%d", *days)
	case "configure", "reconcile":
		if *file == "" {
			fmt.Fprintln(os.Stderr, "--file is required")
			return 2
		}
		raw, err := agentInput(*file, "")
		if err != nil || json.Unmarshal(raw, &body) != nil {
			fmt.Fprintln(os.Stderr, "invalid JSON input")
			return 2
		}
		method, path = "PUT", "/v1/model-gateway/settings"
		if args[0] == "reconcile" {
			if _, err := uuid.Parse(*call); err != nil {
				fmt.Fprintln(os.Stderr, "--call requires a call ID")
				return 2
			}
			path = "/v1/model-gateway/calls/" + *call
		}
	default:
		fmt.Fprintln(os.Stderr, "unknown gateway command")
		return 2
	}
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	raw, err := agentRequest(modelgateway.Socket(paths.Socket), method, path, body)
	if len(raw) > 0 {
		fmt.Println(string(raw))
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}
