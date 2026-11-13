package main

import (
	"encoding/json"
	"fmt"
	"os"
	"slices"
	"strings"

	agentcommands "github.com/ybz21/Roami/agent-runtime"
	clihelp "github.com/ybz21/Roami/internal/cli/help"
	swarmcommand "github.com/ybz21/Roami/internal/cli/swarm"
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
	if len(args) < 2 {
		return false
	}
	path := slices.Clone(args)
	if path[0] == "help" {
		path = path[1:]
	} else if clihelp.IsHelp(path[len(path)-1]) {
		path = path[:len(path)-1]
	} else {
		return false
	}
	if slices.Equal(path, []string{"session"}) || slices.Equal(path, []string{"session", "send"}) {
		return false
	}
	if len(path) > 0 && path[0] == "swarm" && swarmcommand.NativeHelpTopic(path[1:]) {
		return false
	}
	var rows []clihelp.Entry
	seen := map[string]bool{}
	operation := ""
	for name, registered := range agentcommands.Paths() {
		if len(registered) < len(path) || !slices.Equal(registered[:len(path)], path) {
			continue
		}
		if len(registered) == len(path) {
			operation = name
			continue
		}
		child := registered[len(path)]
		if !seen[child] {
			rows = append(rows, clihelp.Entry{Name: child, Description: "查看参数：roami " + strings.Join(append(slices.Clone(path), child), " ") + " -h"})
			seen[child] = true
		}
	}
	if len(rows) == 0 && operation == "" {
		return false
	}
	command := "roami " + strings.Join(path, " ")
	p := clihelp.Page{Command: command, Summary: "使用当前 Agent 上下文的已注册能力", More: "roami agent capability list", Notes: []string{"需当前运行的 Agent 工具上下文；对话、任务与请求身份由宿主提供。"}}
	if operation != "" {
		p.Usage = []string{command + " --input JSON"}
		p.Sections = []clihelp.Section{{Title: "参数", Entries: []clihelp.Entry{{Name: "--input JSON", Description: "一个 JSON 对象；必填字段按能力 schema 提供"}}}}
		p.Examples = []clihelp.Entry{{Name: "roami agent capability show " + operation, Description: "先查看输入 schema 与调用约束"}}
	} else {
		slices.SortFunc(rows, func(a, b clihelp.Entry) int { return strings.Compare(a.Name, b.Name) })
		p.Usage = []string{command + " <命令> --input JSON"}
		p.Sections = []clihelp.Section{{Title: "命令", Entries: rows}}
	}
	_ = p.Render(os.Stdout)
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
