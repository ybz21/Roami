package main

import (
	"slices"
	"testing"

	"github.com/ybz21/Roami/internal/agentruntime"
)

func TestAgentRuntimeDevelopmentChannel(t *testing.T) {
	for _, channel := range []string{"release", "development", "dev", "", "v1.2.3"} {
		for _, initialize := range []bool{true, false} {
			args := agentRuntimeArgs(agentruntime.Paths{}, initialize, channel)
			if got := slices.Contains(args, "--development-rsi"); got != (channel == "development") {
				t.Errorf("channel=%q initialize=%v: RSI=%v", channel, initialize, got)
			}
		}
	}
	if buildChannel != "release" {
		t.Fatal("unflagged builds must default to release")
	}
}
