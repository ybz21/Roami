package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/google/uuid"
	"github.com/ybz21/Roami/internal/agentruntime"
)

type nativeSessionOptions struct {
	Name, Task, Directory, Model, Key string
	FreeOnly, JSON                    bool
}

func parseNativeSessionOptions(args []string) (nativeSessionOptions, error) {
	var options nativeSessionOptions
	for index := 0; index < len(args); index++ {
		word := args[index]
		name, value, inline := strings.Cut(word, "=")
		switch name {
		case "--json":
			options.JSON = true
		case "--detach", "-d":
		case "--free-only":
			options.FreeOnly = true
		case "--kind", "-kind", "--task", "-task", "--dir", "-c", "--model", "-model", "--key":
			if !inline {
				index++
				if index >= len(args) {
					return options, fmt.Errorf("%s requires a value", name)
				}
				value = args[index]
			}
			switch name {
			case "--kind", "-kind":
				if value != "roami" {
					return options, errors.New("session new --kind currently supports roami")
				}
			case "--task", "-task":
				options.Task = value
			case "--dir", "-c":
				options.Directory = value
			case "--model", "-model":
				options.Model = value
			case "--key":
				options.Key = value
			}
		default:
			if strings.HasPrefix(word, "-") || options.Name != "" {
				return options, fmt.Errorf("unexpected new-session argument %q", word)
			}
			options.Name = word
		}
	}
	if strings.TrimSpace(options.Task) == "" {
		return options, errors.New("Roami sessions require --task TEXT")
	}
	if options.Directory != "" {
		absolute, err := filepath.Abs(options.Directory)
		if err != nil {
			return options, err
		}
		options.Directory = absolute
	}
	if options.Key == "" {
		options.Key = uuid.NewString()
	}
	return options, nil
}
func runNativeSessionNew(args []string) int {
	options, err := parseNativeSessionOptions(args)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	if hasAgentToolContext() {
		fmt.Fprintln(os.Stderr, "USE_REGISTERED_CLI_CAPABILITY")
		return 1
	}
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	request := map[string]any{"requestKey": options.Key, "title": options.Name, "task": options.Task, "freeOnly": options.FreeOnly}
	if options.Model != "" {
		request["model"] = options.Model
	}
	if options.Directory != "" {
		request["directory"] = options.Directory
	}
	raw, err := agentRequest(paths.Socket, "POST", "/v1/native-sessions", request)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if options.JSON {
		var reply struct {
			Data json.RawMessage `json:"data"`
		}
		if json.Unmarshal(raw, &reply) != nil || len(reply.Data) == 0 {
			fmt.Fprintln(os.Stderr, "invalid native session receipt")
			return 1
		}
		fmt.Println(string(reply.Data))
	} else {
		var reply struct {
			Data struct {
				Session string `json:"session"`
				TaskID  string `json:"taskId"`
			} `json:"data"`
		}
		if json.Unmarshal(raw, &reply) != nil || reply.Data.Session == "" {
			fmt.Fprintln(os.Stderr, "invalid native session receipt")
			return 1
		}
		fmt.Printf("%s  task=%s\n", reply.Data.Session, reply.Data.TaskID)
	}
	return 0
}
func nativeSessionNewRequested(args []string) bool {
	if len(args) == 0 || args[0] != "new" {
		return false
	}
	for _, word := range args[1:] {
		if word == "--help" || word == "-h" || word == "help" {
			return false
		}
	}
	for _, word := range args[1:] {
		if word == "--kind" || word == "-kind" || strings.HasPrefix(word, "--kind=") || strings.HasPrefix(word, "-kind=") {
			return true
		}
	}
	return false
}
