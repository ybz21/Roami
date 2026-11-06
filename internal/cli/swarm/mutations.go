package swarm

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func isMutation(command string) bool {
	switch command {
	case "plan", "control", "member-add", "member-register", "dependencies", "say", "post", "pause", "resume", "stop", "archive":
		return true
	}
	return false
}
func createSwarm(ctx context.Context, rt runtime.Runtime, o commandOptions, w io.Writer, jsonOutput bool) error {
	if err := o.arguments(1, 1); err != nil {
		return err
	}
	key, err := o.required("key")
	if err != nil {
		return fmt.Errorf("swarm creation requires --key")
	}
	goal, err := o.required("goal")
	if err != nil {
		return err
	}
	body := map[string]any{"name": o.args[0], "commandKey": key, "goal": goal, "mainConversationId": o.value("main-conversation")}
	if dir := o.value("dir"); dir != "" {
		body["target"] = map[string]any{"kind": "new_session", "directory": dir}
	}
	client, err := newRuntimeClient(rt)
	if err != nil {
		return err
	}
	defer client.close()
	raw, err := client.request(ctx, "POST", "/v1/swarms", body)
	if err != nil {
		return err
	}
	return renderReceipt(w, raw, jsonOutput)
}
func readRequest(path string, input io.Reader) (map[string]any, error) {
	reader := input
	if path != "-" {
		file, err := os.Open(path)
		if err != nil {
			return nil, err
		}
		defer file.Close()
		reader = file
	}
	raw, err := io.ReadAll(io.LimitReader(reader, (1<<20)+1))
	if err != nil {
		return nil, err
	}
	if len(raw) > 1<<20 {
		return nil, fmt.Errorf("SWARM_REQUEST_TOO_LARGE")
	}
	var body map[string]any
	if err = json.Unmarshal(raw, &body); err != nil {
		return nil, err
	}
	if body == nil {
		return nil, fmt.Errorf("request must be a JSON object")
	}
	return body, nil
}
func requestIdentity(command string, body map[string]any) error {
	key, ok := body["commandKey"].(string)
	if !ok || strings.TrimSpace(key) == "" {
		return fmt.Errorf("commandKey is required")
	}
	if command == "say" || command == "post" {
		return nil
	}
	revision, ok := body["expectedRevision"].(float64)
	if !ok || revision < 1 || revision != float64(int(revision)) {
		return fmt.Errorf("expectedRevision must be a positive integer")
	}
	return nil
}
func dependencyFlags(o commandOptions) ([]dependency, error) {
	values := []dependency{}
	seen := map[string]bool{}
	for _, value := range o.values["depends-on"] {
		at := strings.LastIndex(value, "@")
		if at < 1 {
			return nil, fmt.Errorf("dependency must be member@revision[#artifact-id]: %s", value)
		}
		member := value[:at]
		revision, artifact, hasArtifact := strings.Cut(value[at+1:], "#")
		if hasArtifact && strings.TrimSpace(artifact) == "" {
			return nil, fmt.Errorf("artifact ID is required after #: %s", value)
		}
		number, err := strconv.Atoi(revision)
		if err != nil || number < 1 {
			return nil, fmt.Errorf("invalid dependency revision: %s", value)
		}
		if seen[member] {
			return nil, fmt.Errorf("duplicate dependency: %s", member)
		}
		seen[member] = true
		values = append(values, dependency{Member: member, Revision: number, ArtifactID: artifact})
	}
	return values, nil
}
func mutateSwarm(ctx context.Context, rt runtime.Runtime, command, path string, o commandOptions, w io.Writer, input io.Reader, jsonOutput bool) error {
	// This marker only restricts shell callers; it never grants an Agent identity.
	if command == "say" && os.Getenv("ROAMI_AGENT_CALLER_ROLE") != "" {
		return fmt.Errorf("AGENT_MESSAGE_IDENTITY_REQUIRED: use the registered roami swarm post --input JSON operation directly, without cd or shell wrappers; public swarm say is for human messages")
	}
	var body map[string]any
	var err error
	suffix := map[string]string{"member-register": "members", "member-add": "plan", "plan": "plan", "dependencies": "dependencies", "control": "control", "say": "messages", "post": "member-posts", "pause": "control", "resume": "control", "stop": "control", "archive": "control"}[command]
	if file := o.value("file"); file != "" {
		if len(o.values) > 1 || o.switches["integration"] || o.switches["clear"] {
			return fmt.Errorf("--file contains the full request; do not mix it with other request options")
		}
		body, err = readRequest(file, input)
		if err != nil {
			return err
		}
		if err = requestIdentity(command, body); err != nil {
			return err
		}
	}
	if body == nil {
		if command == "plan" || command == "control" {
			return fmt.Errorf("%s requires --file <request.json>", command)
		}
		key, err := o.required("key")
		if err != nil {
			return err
		}
		body = map[string]any{"commandKey": key}
		if command != "say" && command != "post" {
			revision, err := o.positive("revision")
			if err != nil {
				return err
			}
			body["expectedRevision"] = revision
		}
		switch command {
		case "pause", "resume", "stop", "archive":
			body["action"] = command
		case "member-add", "member-register":
			executor, err := o.required("executor")
			if err != nil {
				return err
			}
			if executor == "roami" {
				executor = "native"
			}
			switch executor {
			case "native", "codex", "claude", "opencode", "pi":
			default:
				return fmt.Errorf("unsupported executor: %s", executor)
			}
			if command == "member-register" {
				duty, err := o.required("duty")
				if err != nil {
					return err
				}
				body["members"] = []any{map[string]any{"name": o.args[1], "executor": executor, "duty": duty}}
				break
			}
			goal, err := o.required("goal")
			if err != nil {
				return err
			}
			acceptance, err := o.required("acceptance")
			if err != nil {
				return err
			}
			deps, err := dependencyFlags(o)
			if err != nil {
				return err
			}
			title := o.value("title")
			if title == "" {
				title = o.args[1]
			}
			item := map[string]any{"member": o.args[1], "executor": executor, "title": title, "goal": goal, "acceptance": acceptance, "integration": o.switches["integration"], "dependencies": deps}
			if id := o.value("member-id"); id != "" {
				item["memberId"] = id
			}
			body["items"] = []any{item}
		case "dependencies":
			deps, err := dependencyFlags(o)
			if err != nil {
				return err
			}
			if len(deps) == 0 && !o.switches["clear"] {
				return fmt.Errorf("use --depends-on or explicitly --clear")
			}
			if len(deps) > 0 && o.switches["clear"] {
				return fmt.Errorf("--clear cannot be mixed with --depends-on")
			}
			body["dependencies"] = deps
		case "say", "post":
			if strings.TrimSpace(o.args[1]) == "" {
				return fmt.Errorf("message text is required")
			}
			body["text"] = o.args[1]
			if command == "post" {
				for _, field := range []struct{ flag, key string }{{"task", "taskId"}, {"run", "runId"}} {
					value, err := o.required(field.flag)
					if err != nil {
						return err
					}
					body[field.key] = value
				}
				revision, err := o.positive("task-revision")
				if err != nil {
					return err
				}
				body["taskRevision"] = revision
				for _, field := range []struct{ flag, key string }{{"kind", "kind"}, {"message-key", "messageKey"}, {"recipient-member", "recipientMemberId"}} {
					if value := o.value(field.flag); value != "" {
						body[field.key] = value
					}
				}
				if o.value("reply-to") != "" {
					value, err := o.positive("reply-to")
					if err != nil {
						return err
					}
					body["replyTo"] = value
				}
			} else if target := o.value("to"); target != "" && target != "main" {
				revision, err := o.positive("task-revision")
				if err != nil {
					return err
				}
				body["taskRevision"] = revision
			} else if o.value("task-revision") != "" {
				return fmt.Errorf("--task-revision requires --to <member>")
			}
		default:
			return fmt.Errorf("%s requires --file <request.json>", command)
		}
	}
	client, err := newRuntimeClient(rt)
	if err != nil {
		return err
	}
	defer client.close()
	if o.value("file") == "" && (command == "dependencies" || command == "say" && o.value("to") != "" && o.value("to") != "main") {
		value, _, err := readSnapshot(ctx, client, path)
		if err != nil {
			return err
		}
		selector := o.value("to")
		if command == "dependencies" {
			selector = o.args[1]
		}
		work, err := findWork(value, selector)
		if err != nil {
			return err
		}
		if command == "say" && work.TaskID == "" {
			return fmt.Errorf("SWARM_MEMBER_TASK_REQUIRED: member has not been dispatched")
		}
		body["workId"] = work.ID
	}
	raw, err := client.request(ctx, "POST", path+"/"+suffix, body)
	if err != nil {
		return err
	}
	return renderReceipt(w, raw, jsonOutput)
}
