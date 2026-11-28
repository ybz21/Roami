package protocol

import (
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

func TestRequestRejectionUsesOnlyCompleteStructuredErrors(t *testing.T) {
	tests := []struct {
		name  string
		body  string
		want  string
		limit int64
	}{
		{name: "context", body: `{"error":{"code":"context_length_exceeded","message":"private prompt"}}`, want: "context_limit"},
		{name: "output parameter", body: `{"error":{"code":400,"param":"max_tokens"}}`, want: "output_tokens"},
		{name: "nested provider", body: `{"error":{"code":400,"metadata":{"raw":"{\"error\":{\"code\":\"invalid_tool_result\"}}"}}}`, want: "tool_input"},
		{name: "prose", body: `{"error":{"code":400,"message":"context_length_exceeded" }}`},
		{name: "unrecognized parameter", body: `{"error":{"code":"user_value","param":"private prompt"}}`},
		{name: "partial", body: `{"error":{"code":"context_length_exceeded"}}`, limit: 12},
		{name: "oversize", body: `{"error":{"code":"context_length_exceeded","message":"` + strings.Repeat("x", 64<<10) + `"}}`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			observation := NewResponseObservation("openai-completions", time.Now())
			reader := observation.Wrap(io.NopCloser(strings.NewReader(test.body)), false)
			var input io.Reader = reader
			if test.limit > 0 {
				input = io.LimitReader(reader, test.limit)
			}
			if _, err := io.Copy(io.Discard, input); err != nil {
				t.Fatal(err)
			}
			if got := observation.RequestRejection(http.StatusBadRequest); got != test.want {
				t.Fatalf("request rejection = %q, want %q", got, test.want)
			}
			if got := observation.RequestRejection(http.StatusOK); got != "" {
				t.Fatalf("success classified as rejection: %q", got)
			}
		})
	}
}
