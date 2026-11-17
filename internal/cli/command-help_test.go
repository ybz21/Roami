package app

import (
	"bytes"
	"strings"
	"testing"
)

func TestCommandHelpPreservesLiteralArguments(t *testing.T) {
	for _, args := range [][]string{{"send", "session-id", "--help"}, {"sp", "-h"}, {"fork", "session-id", "--help"}} {
		if ShowHelp(args, &bytes.Buffer{}) {
			t.Fatalf("literal argument consumed as help: %v", args)
		}
	}
}

func TestSessionCommandsHaveFocusedHelp(t *testing.T) {
	commands := []string{"ls", "new", "fork", "capture", "resolve", "rename", "send", "keys", "a", "attach", "d", "detach", "kill", "pause", "resume", "reclaim", "compact", "processes", "process-stop", "memory-status", "memory-setup-script", "children", "parent", "parent get", "parent set", "parent clear", "nw", "lw", "kw", "sp", "split", "kp", "status", "info", "completion", "env", "env ls", "env set", "env rm", "env clear", "env push", "db", "db status", "db migrate", "db backup", "db history", "db restore", "db revive", "db set-home", "db link-agent"}
	for _, command := range commands {
		for _, form := range []string{"-h", "--help", "help"} {
			if (command == "sp" || command == "split") && form == "-h" {
				continue
			}
			args := strings.Fields(command)
			if form == "help" {
				args = append([]string{"help"}, args...)
			} else {
				args = append(args, form)
			}
			var out bytes.Buffer
			if !ShowHelp(args, &out) {
				t.Fatalf("help not handled: %v", args)
			}
			canonical := strings.Fields(command)[0]
			switch canonical {
			case "a":
				canonical = "attach"
			case "d":
				canonical = "detach"
			case "split":
				canonical = "sp"
			}
			if !strings.Contains(out.String(), "\n用法\n") || !strings.Contains(out.String(), "roami session "+canonical) {
				t.Fatalf("not focused: %v\n%s", args, out.String())
			}
		}
	}
}
