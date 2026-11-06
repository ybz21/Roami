package swarm

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func Run(rt runtime.Runtime, args []string, w io.Writer) error {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	return runCommand(ctx, rt, args, w, os.Stdin)
}
func runCommand(ctx context.Context, rt runtime.Runtime, args []string, w io.Writer, input io.Reader) error {
	command := "ls"
	if len(args) > 0 {
		if !strings.HasPrefix(args[0], "--") || args[0] == "--help" {
			command, args = args[0], args[1:]
		}
	}
	if command == "help" {
		return showHelp(w, args)
	}
	for _, arg := range args {
		if arg == "--" {
			break
		}
		if arg == "--help" || arg == "-h" {
			return showHelp(w, []string{command})
		}
	}
	if command == "--help" || command == "-h" {
		return showHelp(w, nil)
	}
	if command == "member" {
		if len(args) == 0 {
			return showHelp(w, []string{"member"})
		}
		action := args[0]
		args = args[1:]
		switch action {
		case "ls", "list":
			command = "members"
		case "show":
			command = "work"
		case "add":
			command = "member-add"
		case "register":
			command = "member-register"
		case "inspect":
			command = "member-inspect"
		default:
			return fmt.Errorf("unknown member command: %s", action)
		}
	}
	valueFlags, switchFlags := "", ""
	switch command {
	case "new", "create":
		valueFlags = "key goal main-conversation dir"
	case "ls", "list":
		switchFlags = "archived"
	case "status", "show", "board":
		switchFlags = "follow"
	case "members", "work", "collect":
	case "chat", "feed":
		valueFlags = "limit"
		switchFlags = "follow"
	case "inbox":
		valueFlags = "member before limit task run task-revision"
	case "plan", "control":
		valueFlags = "file"
	case "member-register":
		valueFlags = "file key revision executor duty"
	case "member-inspect":
		valueFlags = "before limit"
	case "member-add":
		valueFlags = "file key revision executor title goal acceptance depends-on member-id"
		switchFlags = "integration"
	case "dependencies":
		valueFlags = "file key revision depends-on"
		switchFlags = "clear"
	case "say":
		valueFlags = "file key to task-revision"
	case "post":
		valueFlags = "file key task run task-revision kind message-key reply-to recipient-member"
	case "pause", "resume", "stop", "archive":
		valueFlags = "key revision"
	default:
		return fmt.Errorf("MANAGED_SWARM_USES_MAIN: unsupported command %q; use roami swarm help", command)
	}
	options, err := parseOptions(args, valueFlags, switchFlags)
	if err != nil {
		return err
	}
	jsonOutput := options.switches["json"] || ui.AgentMode()
	if command == "new" || command == "create" {
		return createSwarm(ctx, rt, options, w, jsonOutput)
	}
	if command == "ls" || command == "list" {
		if err = options.arguments(0, 0); err != nil {
			return err
		}
		client, err := newRuntimeClient(rt)
		if err != nil {
			return err
		}
		defer client.close()
		raw, err := client.request(ctx, "GET", "/v1/swarms", nil)
		if err != nil {
			return err
		}
		if jsonOutput {
			return writeJSON(w, raw)
		}
		var values []snapshot
		if err = responseData(raw, &values); err != nil {
			return err
		}
		return renderDirectory(w, values, options.switches["archived"])
	}
	min, max := 1, 1
	switch command {
	case "member-add", "member-register":
		if options.value("file") == "" {
			min, max = 2, 2
		}
	case "dependencies":
		if options.value("file") == "" {
			min, max = 2, 2
		}
	case "say", "post":
		if options.value("file") == "" {
			min, max = 2, 2
		}
	case "work", "member-inspect":
		min, max = 2, 2
	}
	if err = options.arguments(min, max); err != nil {
		return err
	}
	path, err := swarmPath(options.args[0])
	if err != nil {
		return err
	}
	if isMutation(command) {
		return mutateSwarm(ctx, rt, command, path, options, w, input, jsonOutput)
	}
	client, err := newRuntimeClient(rt)
	if err != nil {
		return err
	}
	defer client.close()
	if command == "inbox" {
		return readInbox(ctx, client, path, options, w, jsonOutput)
	}
	if command == "member-inspect" {
		return inspectMember(ctx, client, path, options, w, jsonOutput)
	}
	value, raw, err := readSnapshot(ctx, client, path)
	if err != nil {
		return err
	}
	if command == "work" {
		return showWork(ctx, client, value, options.args[1], w, jsonOutput)
	}
	if command == "chat" || command == "feed" {
		limit := 50
		if options.value("limit") != "" {
			limit, err = options.positive("limit")
			if err != nil {
				return err
			}
			if limit > 200 {
				return fmt.Errorf("--limit must be 1..200")
			}
		}
		if options.switches["follow"] {
			return followChat(ctx, client, path, value, limit, w, jsonOutput)
		}
		messages := chatMessages(value)
		if len(messages) > limit {
			messages = messages[len(messages)-limit:]
		}
		if jsonOutput {
			return writeJSON(w, map[string]any{"data": messages})
		}
		return renderChat(w, messages)
	}
	if options.switches["follow"] {
		return followView(ctx, client, path, value, command, w, jsonOutput)
	}
	if jsonOutput && command == "members" {
		if value.MemberProtocol == 1 && value.Members != nil {
			return writeJSON(w, map[string]any{"data": value.Members})
		}
		return writeJSON(w, map[string]any{"data": value.Work})
	}
	if jsonOutput && command == "board" {
		return writeJSON(w, map[string]any{"data": boardView(value)})
	}
	if jsonOutput && command != "collect" {
		return writeJSON(w, raw)
	}
	return renderSnapshot(w, value, command, jsonOutput)
}
