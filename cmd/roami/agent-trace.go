package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net/url"
	"os"

	"github.com/ybz21/Roami/internal/agentruntime"
)

func runAgentTrace(args []string) int {
	flags := flag.NewFlagSet("agent trace", flag.ContinueOnError)
	turn := flags.String("turn", "", "turn ID from a send receipt")
	task := flags.String("task", "", "background task ID")
	format := flags.String("format", "json", "json or chrome (Perfetto/Chrome trace-event file)")
	_ = flags.Bool("json", true, "JSON output")
	if err := flags.Parse(args); err != nil {
		if err == flag.ErrHelp {
			return 0
		}
		return 2
	}
	query, err := agentTraceQuery(*turn, *task, *format)
	if err != nil || flags.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "trace requires exactly one of --turn or --task, and --format json|chrome")
		return 2
	}
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	raw, err := agentRequest(paths.Socket, "GET", "/v1/traces?"+query, nil)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return printAgentTrace(raw, *format)
}

func agentTraceQuery(turn, task, format string) (string, error) {
	if (turn == "") == (task == "") || (format != "json" && format != "chrome") {
		return "", fmt.Errorf("INVALID_TRACE_TARGET")
	}
	query := url.Values{"format": {format}}
	if turn != "" {
		query.Set("turnId", turn)
	} else {
		query.Set("taskId", task)
	}
	return query.Encode(), nil
}

func printAgentTrace(raw []byte, format string) int {
	if !json.Valid(raw) {
		fmt.Fprintln(os.Stderr, "INVALID_TRACE_RESPONSE")
		return 1
	}
	if format == "chrome" {
		var response struct {
			Data json.RawMessage `json:"data"`
		}
		if err := json.Unmarshal(raw, &response); err != nil || len(response.Data) == 0 {
			fmt.Fprintln(os.Stderr, "INVALID_TRACE_RESPONSE")
			return 1
		}
		raw = response.Data
	}
	fmt.Println(string(raw))
	return 0
}
