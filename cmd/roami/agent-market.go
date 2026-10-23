package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net/url"
	"os"

	"github.com/ybz21/Roami/internal/agentruntime"
)

func runAgentMarket(args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" {
		fmt.Println("roami agent capability market sources\nroami agent capability market search --input '{\"source\":\"skills-sh\",\"query\":\"find-skills\"}'\nroami agent capability market preview --input '{\"source\":\"skills-sh\",\"id\":\"OWNER/REPO/SKILL\",\"version\":\"\"}'\nroami agent capability market install --input '{\"previewId\":\"RETURNED_ID\",\"option\":0}'\nPreview pins the downloaded option for ten minutes; install is separate and never overwrites an existing name. MCP is registered disconnected. npm CLI downloads its fixed package on first invocation. Agent contexts use the same role and receipt checks; professional tasks may add --context FILE and --call REQUEST_ID.")
		return 0
	}
	verb := args[0]
	if verb != "sources" && verb != "search" && verb != "preview" && verb != "install" {
		fmt.Fprintln(os.Stderr, "unknown marketplace command")
		return 2
	}
	flags := flag.NewFlagSet("agent capability market "+verb, flag.ContinueOnError)
	input := flags.String("input", "{}", "JSON arguments")
	contextFile := flags.String("context", "", "private professional task context file")
	requestID := flags.String("call", "", "professional request ID")
	_ = flags.Bool("json", true, "JSON output")
	if err := flags.Parse(args[1:]); err != nil {
		if err == flag.ErrHelp {
			return 0
		}
		return 2
	}
	var payload map[string]any
	if flags.NArg() != 0 || len(*input) > 100000 || json.Unmarshal([]byte(*input), &payload) != nil || payload == nil {
		fmt.Fprintln(os.Stderr, "input must be a JSON object")
		return 2
	}
	if *contextFile != "" || os.Getenv("ROAMI_AGENT_TURN_ID") != "" {
		call := []string{"call", "market_" + verb, "--input", *input}
		if *contextFile != "" {
			call = append(call, "--context", *contextFile)
		}
		if *requestID != "" {
			call = append(call, "--call", *requestID)
		}
		return runAgentCapability(call)
	}
	method, path := "GET", "/v1/capability-markets"
	var body any
	switch verb {
	case "sources":
		if len(payload) != 0 {
			return 2
		}
	case "search":
		for key := range payload {
			if key != "source" && key != "query" && key != "cursor" {
				return 2
			}
		}
		source, ok := payload["source"].(string)
		query, queryOK := payload["query"].(string)
		if !ok || !queryOK || len(payload) > 3 {
			return 2
		}
		values := url.Values{"query": []string{query}}
		if cursor, exists := payload["cursor"]; exists {
			text, valid := cursor.(string)
			if !valid {
				return 2
			}
			values.Set("cursor", text)
		}
		path += "/" + url.PathEscape(source) + "/search?" + values.Encode()
	case "preview":
		method, path, body = "POST", path+"/prepare", payload
	case "install":
		method, path, body = "POST", path+"/install", payload
	}
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
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
