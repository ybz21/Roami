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
	commands := []string{"ls", "new", "fork", "capture", "resolve", "rename", "send", "keys", "a", "attach", "d", "detach", "kill", "pause", "resume", "reclaim", "compact", "processes", "process-stop", "memory-status", "memory-setup-script", "children", "parent", "parent get", "parent set", "parent clear", "window", "window new", "window ls", "window select", "window kill", "pane", "pane ls", "pane split", "pane kill", "nw", "lw", "kw", "sp", "split", "kp", "status", "info", "completion", "env", "env ls", "env set", "env rm", "env clear", "env push", "db", "db status", "db migrate", "db backup", "db history", "db restore", "db revive", "db set-home", "db link-agent"}
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

func TestSessionHelpAllListsOpsAndLegacyAliases(t *testing.T) {
	var out bytes.Buffer
	if !ShowHelp([]string{"help", "--all"}, &out) {
		t.Fatal("help --all not handled")
	}
	for _, want := range []string{"roami session (全部命令)", "memory-setup-script", "nw / lw / kw", "sp / split / kp", "window <new|ls|select|kill>"} {
		if !strings.Contains(out.String(), want) {
			t.Fatalf("help --all missing %q:\n%s", want, out.String())
		}
	}
}
