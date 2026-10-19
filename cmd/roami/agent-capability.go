package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net/url"
	"os"
	"strconv"

	"github.com/ybz21/Roami/internal/agentruntime"
)

func runAgentCapability(args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		fmt.Println("roami agent capability list [--kind all|mcp|skill|cli] [--query TEXT] [--limit 10] [--offset 0]\nroami agent capability show NAME\nroami agent capability call NAME --input JSON --turn TURN --call CALL\nCalls require the running Agent tool context; bash supplies it automatically. List and show are read-only.")
		return 0
	}
	sub := args[0]
	if sub != "list" && sub != "show" && sub != "call" {
		fmt.Fprintln(os.Stderr, "unknown capability command")
		return 2
	}
	name := ""
	rest := args[1:]
	if sub != "list" {
		if len(rest) == 0 {
			fmt.Fprintln(os.Stderr, "capability name required")
			return 2
		}
		name = rest[0]
		rest = rest[1:]
	}
	flags := flag.NewFlagSet("agent capability "+sub, flag.ContinueOnError)
	query := flags.String("query", "", "capability name or intent")
	kind := flags.String("kind", "all", "all, mcp, skill or cli")
	limit := flags.Int("limit", 10, "page size, 1 to 20")
	offset := flags.Int("offset", 0, "catalog offset")
	input := flags.String("input", "{}", "JSON arguments")
	turn := flags.String("turn", os.Getenv("ROAMI_AGENT_TURN_ID"), "running turn ID")
	call := flags.String("call", os.Getenv("ROAMI_AGENT_TOOL_CALL_ID"), "running tool call ID")
	_ = flags.Bool("json", true, "JSON output")
	if err := flags.Parse(rest); err != nil {
		if err == flag.ErrHelp {
			return 0
		}
		return 2
	}
	if flags.NArg() != 0 {
		return 2
	}
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	method, path := "GET", "/v1/tool-directory"
	var body any
	switch sub {
	case "list":
		if *kind != "all" && *kind != "mcp" && *kind != "skill" && *kind != "cli" || *limit < 1 || *limit > 20 || *offset < 0 {
			fmt.Fprintln(os.Stderr, "invalid kind or pagination")
			return 2
		}
		values := url.Values{}
		values.Set("query", *query)
		values.Set("kind", *kind)
		values.Set("limit", strconv.Itoa(*limit))
		values.Set("offset", strconv.Itoa(*offset))
		path += "?" + values.Encode()
	case "show":
		path += "/" + url.PathEscape(name)
	case "call":
		if *turn == "" || *call == "" || len(*input) > 100000 {
			fmt.Fprintln(os.Stderr, "running --turn and --call context required")
			return 2
		}
		var arguments map[string]any
		if err := json.Unmarshal([]byte(*input), &arguments); err != nil || arguments == nil {
			fmt.Fprintln(os.Stderr, "input must be a JSON object")
			return 2
		}
		method, path, body = "POST", path+"/"+url.PathEscape(name)+"/call", map[string]any{"turnId": *turn, "toolCallId": *call, "arguments": arguments}
	}
	raw, err := agentRequest(paths.Socket, method, path, body)
	if len(raw) > 0 {
		fmt.Println(string(raw))
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}
