package main

import (
	"strings"
	"testing"
)

func TestNativeSessionModelOptions(t *testing.T) {
	options, err := parseNativeSessionOptions([]string{"Review", "--kind", "roami", "--task", "read files", "-model", "free-pool", "--free-only", "--json", "--key", "stable"})
	if err != nil || options.Model != "free-pool" || !options.FreeOnly || options.Task != "read files" || options.Key != "stable" {
		t.Fatalf("lost selection: %+v %v", options, err)
	}
	for _, args := range [][]string{{"--kind", "roami"}, {"--kind", "codex", "--task", "test"}, {"--model"}, {"--kind", "roami", "--task", "test", "--size", "80x24"}} {
		if _, err := parseNativeSessionOptions(args); err == nil {
			t.Fatal("invalid options accepted", args)
		}
	}
}
func TestNativeSessionDispatchLeavesShellAndHelpUntouched(t *testing.T) {
	for _, command := range []string{"new label --kind roami --model free-pool --task test", "new --kind=roami --task=test"} {
		if !nativeSessionNewRequested(strings.Fields(command)) {
			t.Fatal(command)
		}
	}
	for _, command := range []string{"new label --dir .", "new --kind roami --help", "fork parent name", "new --task text"} {
		if nativeSessionNewRequested(strings.Fields(command)) {
			t.Fatal(command)
		}
	}
}
