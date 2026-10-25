package main

import (
	"encoding/json"
	"fmt"
	"os"
	"slices"
	"strings"

	agentcommands "github.com/ybz21/Roami/agent-runtime"
)

// A named command uses the same admitted tool context as its legacy transport.
func boundCommand(args []string) (string, string, bool) {
	for name, path := range agentcommands.Paths() {
		if len(args) >= len(path)+1 && slices.Equal(args[:len(path)], path) && args[len(path)] == "--input" {
			if len(args) != len(path)+2 || !json.Valid([]byte(args[len(path)+1])) {
				return "", "", true
			}
			return name, args[len(path)+1], true
		}
	}
	return "", "", false
}

func runBoundCommand(args []string) (bool, int) {
	if len(args) >= 3 && slices.Equal(args[:3], []string{"agent", "capability", "market"}) {
		return false, 0
	}
	name, input, matched := boundCommand(args)
	if !matched {
		return false, 0
	}
	if name == "" {
		fmt.Fprintln(os.Stderr, "expected --input JSON object")
		return true, 2
	}
	return true, runAgentCapability([]string{"call", name, "--input", input})
}

func commandFamilyHelp(args []string) bool {
	if len(args) < 2 || (args[len(args)-1] != "help" && args[len(args)-1] != "--help") {
		return false
	}
	prefix := args[:len(args)-1]
	if !slices.Equal(prefix, []string{"agent", "task"}) && !slices.Equal(prefix, []string{"agent", "memory"}) && !slices.Equal(prefix, []string{"agent", "target"}) && !slices.Equal(prefix, []string{"agent", "host"}) {
		return false
	}
	var lines []string
	for _, path := range agentcommands.Paths() {
		if len(path) >= len(prefix) && slices.Equal(path[:len(prefix)], prefix) {
			lines = append(lines, "roami "+strings.Join(path, " ")+" --input JSON")
		}
	}
	slices.Sort(lines)
	fmt.Println(strings.Join(lines, "\n") + "\nRequires the running Agent tool context; conversation, task and request identity are supplied by the host.")
	return true
}

func managedChrome(args []string) (bool, int) {
	if len(args) == 0 {
		return false, 0
	}
	resource, observation := "", ""
	var positionals []string
	for i := 1; i < len(args); i++ {
		if args[i] == "--resource" || args[i] == "--observation" {
			if i+1 >= len(args) {
				return true, 2
			}
			if args[i] == "--resource" {
				if resource != "" {
					return true, 2
				}
				resource = args[i+1]
			} else {
				if observation != "" {
					return true, 2
				}
				observation = args[i+1]
			}
			i++
		} else {
			positionals = append(positionals, args[i])
		}
	}
	if resource == "" && observation == "" {
		return false, 0
	}
	name := "browser_act"
	payload := map[string]any{"observationId": observation, "kind": args[0]}
	if resource != "" && observation == "" && len(positionals) == 0 && (args[0] == "observe" || args[0] == "screenshot") {
		name = "browser_observe"
		payload = map[string]any{"resourceId": resource}
	} else if observation != "" && resource == "" {
		switch args[0] {
		case "goto":
			if len(positionals) != 1 {
				return true, 2
			}
			payload["url"] = positionals[0]
		case "click":
			if len(positionals) != 1 {
				return true, 2
			}
			payload["selector"] = positionals[0]
		case "fill", "type":
			if len(positionals) != 2 {
				return true, 2
			}
			payload["selector"] = positionals[0]
			payload["text"] = positionals[1]
		case "press":
			if len(positionals) != 1 {
				return true, 2
			}
			payload["key"] = positionals[0]
		default:
			return true, 2
		}
	} else {
		return true, 2
	}
	data, _ := json.Marshal(payload)
	return true, runAgentCapability([]string{"call", name, "--input", string(data)})
}
