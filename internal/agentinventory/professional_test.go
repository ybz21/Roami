package agentinventory

import (
	"reflect"
	"testing"
)

func TestProfessionalInstallArgs(t *testing.T) {
	for kind, want := range map[string][]string{
		"codex":    {"install", "-g", "@openai/codex"},
		"claude":   {"install", "-g", "@anthropic-ai/claude-code"},
		"opencode": {"install", "-g", "opencode-ai"},
		"pi":       {"install", "-g", "--ignore-scripts", "@earendil-works/pi-coding-agent"},
	} {
		got, err := ProfessionalInstallArgs(kind)
		if err != nil || !reflect.DeepEqual(got, want) {
			t.Fatalf("%s: %v, %v", kind, got, err)
		}
	}
	for _, kind := range []string{"", "unknown", "codex;echo injected", "--prefix=/tmp"} {
		if _, err := ProfessionalInstallArgs(kind); err == nil {
			t.Fatalf("accepted unsupported kind %q", kind)
		}
	}
}
