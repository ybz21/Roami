package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/url"
	"os"
	"strings"
)

func runProjectOKR(args []string) int {
	if len(args) == 2 && args[0] == "record" && (args[1] == "help" || args[1] == "--help") {
		fmt.Println(`roami project okr record PROJECT --file JSON|- --json
Single explicit observation: {"revision":N,"metricId":"ID","date":"YYYY-MM-DD","value":NUMBER,"note":"Evidence"}.
Skill batch (requires projectFiles.connectorSkillBatches): {"revision":N,"batch":{"id":"32-lowercase-hex","connectorId":"SOURCE","packageSha256":"CONFIRMED_SHA256","sourceIdentity":"CONFIRMED_ID","date":"YYYY-MM-DD","capturedAt":"RFC3339","windowStart":"RFC3339","windowEnd":"RFC3339","values":[{"metricId":"ID","unit":"CONFIRMED_UNIT","value":NUMBER}],"evidence":[{"path":"PROJECT_RELATIVE_FILE","sha256":"RAW_SHA256"}]}}.
Read the confirmed connectors first. Day windows are [start,end); snapshot windows have equal endpoints. Main reviews external source semantics. The host hashes and archives the referenced bytes; it never launches the Skill. After an unknown outcome, show the workspace and find connectorBatches by batch id, then retry the exact original payload/key if needed. A receipt confirms data publication, not task acceptance or an active schedule.`)
		return 0
	}
	if len(args) == 2 && args[0] == "memory" && (args[1] == "help" || args[1] == "--help") {
		fmt.Println(`roami project okr memory PROJECT --file JSON|- --json
Read 'roami project okr show PROJECT --json' first. Append real new knowledge with:
{"mode":"append","content":"New verified knowledge","expectedSha256":"CURRENT_MEMORY_SHA256"}
Full replacement uses mode=replace. Prior bytes are retained in memory/history/<sha256>.md.
Never probe a live write endpoint to discover its schema. A conflict requires rereading.`)
		return 0
	}
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" {
		fmt.Println("roami project okr show|save|sync|memory|record|collect|review PROJECT [--file JSON|-] [--server URL] [--json]\nWrites require the current revision in the JSON object; collect also requires --file. A conflict never retries a write.")
		return 0
	}
	action := args[0]
	method, suffix := "", ""
	switch action {
	case "show":
		method = "GET"
	case "save":
		method = "PUT"
	case "sync":
		method, suffix = "POST", "/sync"
	case "memory":
		method, suffix = "PUT", "/memory"
	case "record":
		method, suffix = "POST", "/observations"
	case "collect":
		method, suffix = "POST", "/collect"
	case "review":
		method, suffix = "POST", "/reviews"
	default:
		fmt.Fprintln(os.Stderr, "Unknown OKR command:", action)
		return 2
	}
	fs := flag.NewFlagSet("project okr "+action, flag.ContinueOnError)
	server := fs.String("server", "", "Roami server")
	file := fs.String("file", "", "JSON file, or - for stdin")
	asJSON := fs.Bool("json", false, "JSON output")
	var options, ids []string
	for i := 1; i < len(args); i++ {
		if strings.HasPrefix(args[i], "--") {
			options = append(options, args[i])
			if !strings.Contains(args[i], "=") && args[i] != "--json" && i+1 < len(args) {
				i++
				options = append(options, args[i])
			}
		} else {
			ids = append(ids, args[i])
		}
	}
	if err := fs.Parse(options); err != nil {
		return 2
	}
	fail := func(err error) int {
		var apiErr *apiFailure
		if *asJSON {
			if errors.As(err, &apiErr) {
				fmt.Println(string(apiErr.raw))
			} else {
				encoded, _ := json.Marshal(map[string]any{"error": map[string]string{"code": "CLI_ERROR", "message": err.Error()}})
				fmt.Println(string(encoded))
			}
		} else {
			fmt.Fprintln(os.Stderr, err)
		}
		return 1
	}
	if len(ids) != 1 || strings.TrimSpace(ids[0]) == "" {
		return fail(fmt.Errorf("Exactly one project ID is required"))
	}
	var body any
	if method != "GET" {
		if *file == "" {
			return fail(fmt.Errorf("--file JSON or --file - is required"))
		}
		reader := io.Reader(os.Stdin)
		if *file != "-" {
			input, err := os.Open(*file)
			if err != nil {
				return fail(err)
			}
			defer input.Close()
			reader = input
		}
		content, err := io.ReadAll(io.LimitReader(reader, (1<<20)+1))
		if err != nil {
			return fail(err)
		}
		content = bytes.TrimSpace(content)
		if len(content) > 1<<20 || len(content) == 0 || content[0] != '{' || !json.Valid(content) {
			return fail(fmt.Errorf("Input must be one JSON object of at most 1 MiB"))
		}
		body = json.RawMessage(content)
	} else if *file != "" {
		return fail(fmt.Errorf("show does not accept --file"))
	}
	connection, err := connectAPI(*server)
	if err != nil {
		return fail(err)
	}
	raw, err := connection.request(method, "/api/projects/"+url.PathEscape(ids[0])+"/okr"+suffix, body)
	if err != nil {
		return fail(err)
	}
	fmt.Println(string(raw))
	return 0
}
