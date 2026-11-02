package main

import "testing"

func TestMarketplaceHelpAndInvalidInputDoNotRequireRuntime(t *testing.T) {
	t.Setenv("ROAMI_AGENT_TURN_ID", "")
	for _, args := range [][]string{{"help"}, {"search", "--help"}} {
		if code := runAgentMarket(args); code != 0 {
			t.Fatalf("help %v: %d", args, code)
		}
	}
	for _, args := range [][]string{{"missing"}, {"search", "--input", "[]"}, {"search", "--input", "{}"}, {"sources", "extra"}, {"search", "--input", `{"source":"skills-sh","query":"x","unknown":true}`}} {
		if code := runAgentMarket(args); code != 2 {
			t.Fatalf("invalid arguments %v: %d", args, code)
		}
	}
	if handled, _ := runBoundCommand([]string{"agent", "capability", "market", "search", "--input", `{}`, "--context", "/private/context"}); handled {
		t.Fatal("market parser lost professional context flags to generic interception")
	}
}
