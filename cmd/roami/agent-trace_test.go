package main

import (
	"net/url"
	"testing"
)

func TestAgentTraceQueryRequiresOneTargetAndEscapesCorrelationIDs(t *testing.T) {
	for _, tc := range []struct{ turn, task, format string }{
		{"", "", "json"}, {"turn", "task", "json"}, {"turn", "", "other"},
	} {
		if _, err := agentTraceQuery(tc.turn, tc.task, tc.format); err == nil {
			t.Fatalf("accepted ambiguous trace: %+v", tc)
		}
	}
	for _, target := range []string{"turn", "task"} {
		turn, task := "", ""
		if target == "turn" {
			turn = "id&taskId=foreign"
		} else {
			task = "id&turnId=foreign"
		}
		raw, err := agentTraceQuery(turn, task, "chrome")
		if err != nil {
			t.Fatal(err)
		}
		query, err := url.ParseQuery(raw)
		if err != nil || len(query) != 2 || query.Get(target+"Id") != turn+task || query.Get("format") != "chrome" {
			t.Fatalf("trace query lost target isolation: %s", raw)
		}
	}
}

func TestAgentTraceRejectsTruncatedResponseInsteadOfWritingACorruptArtifact(t *testing.T) {
	for _, format := range []string{"json", "chrome"} {
		if printAgentTrace([]byte(`{"data":{"traceEvents":[`), format) != 1 {
			t.Fatalf("accepted truncated %s trace", format)
		}
	}
}
