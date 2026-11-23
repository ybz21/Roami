package protocol

import (
	"strings"
	"testing"
)

const billableEvents = "data: {\"choices\":[{\"delta\":{\"content\":\"hello\"},\"finish_reason\":\"stop\"}]}\n\ndata: {\"choices\":[],\"usage\":{\"prompt_tokens\":1000000,\"completion_tokens\":125000,\"prompt_tokens_details\":{\"cached_tokens\":500000}}}\n\ndata: [DONE]\n\n"

func TestUsageCaptureChunkBoundariesAndInvalidUsage(t *testing.T) {
	c := usageCapture{stream: true}
	for _, value := range []byte(billableEvents) {
		c.feed([]byte{value})
	}
	if u := c.finish(true); u == nil || u.Cached != 500000 {
		t.Fatalf("fragmented usage: %+v", u)
	}
	for _, body := range []string{
		`{"usage":{"prompt_tokens":true,"completion_tokens":1}}`,
		`{"usage":{"prompt_tokens":1,"completion_tokens":1,"prompt_tokens_details":{"cached_tokens":2}}}`,
		`{"usage":{"prompt_tokens":null,"completion_tokens":1}}`,
		`{"usage":{"prompt_tokens":-1,"completion_tokens":1}}`,
	} {
		if parseUsage([]byte(body)) != nil {
			t.Fatalf("invalid usage accepted: %s", body)
		}
	}
	c = usageCapture{stream: true}
	c.feed([]byte(strings.TrimSuffix(billableEvents, "data: [DONE]\n\n")))
	if c.finish(true) != nil {
		t.Fatal("incomplete stream charged as complete")
	}
	c = usageCapture{stream: true}
	c.feed([]byte(billableEvents))
	if c.finish(false) == nil {
		t.Fatal("terminal usage lost when the caller closes after DONE")
	}
	c = usageCapture{stream: true}
	c.feed([]byte("data: " + strings.Repeat("x", 2<<20) + "\n" + billableEvents))
	if c.finish(true) != nil || len(c.buffer) > 1<<20 {
		t.Fatal("unbounded or invalid event accepted")
	}
}

func TestMessagesUsageSplitEventsAndMissingTerminal(t *testing.T) {
	events := "data: {\"type\":\"message_start\",\"message\":{\"usage\":{\"input_tokens\":10,\"output_tokens\":0,\"cache_read_input_tokens\":6,\"cache_creation_input_tokens\":4}}}\n\ndata: {\"type\":\"message_delta\",\"usage\":{\"output_tokens\":8}}\n\ndata: {\"type\":\"message_stop\"}\n\n"
	c := Capture{protocol: "anthropic-messages", stream: true}
	for _, b := range []byte(events) {
		c.Feed([]byte{b})
	}
	usage := c.Finish(true)
	if usage == nil || usage.Input != 20 || usage.Cached != 6 || usage.Output != 8 {
		t.Fatalf("bad Messages accounting: %+v", usage)
	}
	c = Capture{protocol: "anthropic-messages", stream: true}
	c.Feed([]byte(strings.ReplaceAll(events, "data: {\"type\":\"message_stop\"}\n\n", "")))
	if c.Finish(true) != nil {
		t.Fatal("missing terminal was treated as complete")
	}
}
