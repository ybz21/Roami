package main

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/url"
	"os"
	"strconv"
	"syscall"

	"github.com/ybz21/Roami/internal/agentruntime"
)

func runAgentCapability(args []string) int {
	if len(args) > 0 && args[0] == "market" {
		return runAgentMarket(args[1:])
	}
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		fmt.Println("roami agent capability market help")
		fmt.Println("roami agent capability list [--kind all|mcp|skill|cli|tool] [--query TEXT] [--limit 10] [--offset 0]\nroami agent capability show NAME\nroami agent capability read SKILL --context FILE [--reference references/FILE.md]\nroami agent capability call NAME --input JSON --context FILE [--call REQUEST_ID]\nroami agent capability call NAME --input JSON --turn TURN --call CALL\nProfessional calls require the private context file issued for an active Roami task. Reuse --call only to recover the same invocation; unknown outcomes must not be replayed. Native bash supplies turn/call context automatically. List and show are read-only.")
		return 0
	}
	sub := args[0]
	if sub != "list" && sub != "show" && sub != "call" && sub != "read" {
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
	kind := flags.String("kind", "all", "all, mcp, skill, cli or tool")
	limit := flags.Int("limit", 10, "page size, 1 to 20")
	offset := flags.Int("offset", 0, "catalog offset")
	input := flags.String("input", "{}", "JSON arguments")
	turn := flags.String("turn", os.Getenv("ROAMI_AGENT_TURN_ID"), "running turn ID")
	call := flags.String("call", os.Getenv("ROAMI_AGENT_TOOL_CALL_ID"), "running tool call ID")
	contextFile := flags.String("context", "", "private professional task context file")
	reference := flags.String("reference", "", "Skill reference path")
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
		if *kind != "all" && *kind != "mcp" && *kind != "skill" && *kind != "cli" && *kind != "tool" || *limit < 1 || *limit > 20 || *offset < 0 {
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
	case "call", "read":
		if (sub == "read" && *contextFile == "") || (*contextFile == "" && (*turn == "" || *call == "")) || len(*input) > 100000 {
			fmt.Fprintln(os.Stderr, "running --turn and --call context required")
			return 2
		}
		var arguments map[string]any
		if err := json.Unmarshal([]byte(*input), &arguments); err != nil || arguments == nil {
			fmt.Fprintln(os.Stderr, "input must be a JSON object")
			return 2
		}
		if sub == "read" {
			arguments = map[string]any{"name": name}
			if *reference != "" {
				arguments["reference"] = *reference
			}
			name = "skill_read"
		}
		method, path, body = "POST", path+"/"+url.PathEscape(name)+"/call", map[string]any{"turnId": *turn, "toolCallId": *call, "arguments": arguments}
		if *contextFile != "" {
			explicitCall := false
			flags.Visit(func(flag *flag.Flag) {
				if flag.Name == "call" {
					explicitCall = true
				}
			})
			if !explicitCall {
				*call = ""
			}
			context, err := readCapabilityContext(*contextFile)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				return 2
			}
			if *call == "" {
				var id [16]byte
				if _, err := rand.Read(id[:]); err != nil {
					fmt.Fprintln(os.Stderr, err)
					return 1
				}
				*call = hex.EncodeToString(id[:])
			}
			body = map[string]any{"executionContext": context, "requestId": *call, "arguments": arguments}
		}
	}
	raw, err := agentRequest(paths.Socket, method, path, body)
	if len(raw) > 0 {
		fmt.Println(string(raw))
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		if *contextFile != "" {
			fmt.Fprintf(os.Stderr, "request ID: %s; recover only with this ID and the same arguments\n", *call)
		}
		return 1
	}
	if *contextFile != "" && method == "POST" {
		var receipt struct {
			Data struct {
				State string `json:"state"`
			} `json:"data"`
		}
		if json.Unmarshal(raw, &receipt) != nil || receipt.Data.State != "succeeded" {
			fmt.Fprintf(os.Stderr, "capability outcome: %s (request ID: %s)\n", receipt.Data.State, *call)
			return 1
		}
	}
	return 0
}

func readCapabilityContext(path string) (map[string]any, error) {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, fmt.Errorf("CAPABILITY_CONTEXT_UNAVAILABLE")
	}
	f := os.NewFile(uintptr(fd), path)
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 4096 {
		return nil, fmt.Errorf("CAPABILITY_CONTEXT_PRIVATE_FILE_REQUIRED")
	}
	raw, err := io.ReadAll(io.LimitReader(f, 4097))
	var context map[string]any
	if err != nil || len(raw) > 4096 || json.Unmarshal(raw, &context) != nil || context == nil {
		return nil, fmt.Errorf("INVALID_CAPABILITY_CONTEXT")
	}
	return context, nil
}
