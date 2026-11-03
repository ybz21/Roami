package swarm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"time"

	"github.com/ybz21/Roami/internal/agentruntime"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

var managedID = regexp.MustCompile(`^sw-[a-f0-9]{32}$`)

// Managed commands use the same runtime service as Web and Main tools.
func managedCommand(rt runtime.Runtime, sub string, args []string, w io.Writer) (bool, error) {
	mainID := ""
	for i, arg := range args {
		if arg == "--main-conversation" && i+1 < len(args) {
			mainID = args[i+1]
		}
	}
	if (sub == "new" || sub == "create") && mainID != "" {
		if len(args) == 0 {
			return true, fmt.Errorf("name is required")
		}
		spec := map[string]any{"name": args[0], "mainConversationId": mainID}
		for i := 1; i < len(args); i++ {
			if i+1 >= len(args) {
				return true, fmt.Errorf("value required: %s", args[i])
			}
			value := args[i+1]
			switch args[i] {
			case "--main-conversation":
			case "--goal":
				spec["goal"] = value
			case "--key":
				spec["commandKey"] = value
			case "--dir":
				spec["target"] = map[string]any{"kind": "new_session", "directory": value}
			default:
				return true, fmt.Errorf("unsupported managed swarm option: %s", args[i])
			}
			i++
		}
		if spec["commandKey"] == nil {
			return true, fmt.Errorf("managed swarm creation requires --key")
		}
		return true, managedRequest(rt, "POST", "/v1/swarms", spec, w)
	}
	if sub == "managed-list" {
		return true, managedRequest(rt, "GET", "/v1/swarms", nil, w)
	}
	if len(args) == 0 || !managedID.MatchString(args[0]) {
		return false, nil
	}
	path := "/v1/swarms/" + url.PathEscape(args[0])
	switch sub {
	case "status", "board", "feed", "collect":
		return true, managedRequest(rt, "GET", path, nil, w)
	case "plan", "control", "say", "post", "dependencies":
		if len(args) != 3 || args[1] != "--file" {
			return true, fmt.Errorf("usage: roami session swarm %s <swarm-id> --file <request.json>", sub)
		}
		raw, err := os.ReadFile(args[2])
		if err != nil {
			return true, err
		}
		if len(raw) > 1<<20 {
			return true, fmt.Errorf("SWARM_REQUEST_TOO_LARGE")
		}
		var body map[string]any
		if err = json.Unmarshal(raw, &body); err != nil {
			return true, err
		}
		suffix := map[string]string{"plan": "plan", "control": "control", "say": "messages", "post": "member-posts", "dependencies": "dependencies"}[sub]
		return true, managedRequest(rt, "POST", path+"/"+suffix, body, w)
	default:
		return true, fmt.Errorf("MANAGED_SWARM_USES_MAIN: use plan, control or say; done cannot override verification")
	}
}

func managedRequest(rt runtime.Runtime, method, path string, body any, w io.Writer) error {
	paths, err := agentruntime.Resolve(rt.HomeDir, rt.DataDir)
	if err != nil {
		return err
	}
	var raw []byte
	if body != nil {
		raw, err = json.Marshal(body)
		if err != nil {
			return err
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, method, "http://roami-agent"+path, bytes.NewReader(raw))
	if err != nil {
		return err
	}
	request.Header.Set("X-Roami-Owner", "local")
	request.Header.Set("Content-Type", "application/json")
	transport := agentruntime.Transport(paths.Socket)
	defer transport.CloseIdleConnections()
	response, err := (&http.Client{Transport: transport}).Do(request)
	if err != nil {
		return fmt.Errorf("AGENT_RUNTIME_UNAVAILABLE: %w", err)
	}
	defer response.Body.Close()
	output, err := io.ReadAll(io.LimitReader(response.Body, 8<<20))
	if err != nil {
		return err
	}
	if response.StatusCode >= 400 {
		return fmt.Errorf("managed swarm HTTP %d: %s", response.StatusCode, output)
	}
	_, err = fmt.Fprintln(w, string(output))
	return err
}
