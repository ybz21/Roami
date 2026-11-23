package modelgateway

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	wireprotocol "github.com/ybz21/Roami/internal/modelgateway/protocol"
	"github.com/ybz21/Roami/internal/modelgateway/protocoltest"
)

func TestClassifierStreamReturnsOneJSONMessageWithActualUsage(t *testing.T) {
	body, _ := json.Marshal(protocoltest.Request("anthropic-messages", false))
	wire, bridge, err := wireprotocol.Prepare(body, "anthropic-messages", "openai-completions", "configured-model", true)
	if err != nil {
		t.Fatal(err)
	}
	var request map[string]any
	if err := json.Unmarshal(wire, &request); err != nil {
		t.Fatal(err)
	}
	if request["stream"] != true || request["model"] != "configured-model" {
		t.Fatalf("changed downstream mode or route: %s", wire)
	}
	if objectValue(request["stream_options"])["include_usage"] != true {
		t.Fatal("usage was not requested")
	}
	upstream := httptest.NewRecorder()
	protocoltest.WriteResponse(upstream, "openai-completions", true)
	bridge.SetResponseModel("saved-alias")
	out := httptest.NewRecorder()
	capture := wireprotocol.NewCapture("openai-completions", true)
	complete, err := bridge.Forward(out, upstream.Result(), capture)
	if err != nil || !complete || out.Code != 200 {
		t.Fatalf("conversion: %v %v %s", complete, err, out.Body)
	}
	if !strings.Contains(out.Header().Get("Content-Type"), "application/json") || bytes.Contains(out.Body.Bytes(), []byte("data:")) {
		t.Fatalf("classifier received SSE: %s", out.Body)
	}
	var result map[string]any
	if err := json.Unmarshal(out.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if result["model"] != "saved-alias" || result["type"] != "message" {
		t.Fatalf("lost client model: %+v", result)
	}
	usage := objectValue(result["usage"])
	if usage["input_tokens"] != float64(80) || usage["output_tokens"] != float64(7) || usage["cache_read_input_tokens"] != float64(20) {
		t.Fatalf("changed usage: %+v", usage)
	}
	content := arrayValue(result["content"])
	if len(content) != 2 || objectValue(content[0])["text"] != "Ready" || objectValue(content[1])["type"] != "tool_use" {
		t.Fatalf("lost result: %+v", content)
	}
}

func TestClassifierStreamNeverTurnsTruncatedOutputIntoSuccess(t *testing.T) {
	body, _ := json.Marshal(protocoltest.Request("anthropic-messages", false))
	_, bridge, err := wireprotocol.Prepare(body, "anthropic-messages", "openai-completions", "configured-model", true)
	if err != nil {
		t.Fatal(err)
	}
	upstream := httptest.NewRecorder()
	upstream.Header().Set("Content-Type", "text/event-stream")
	_, _ = upstream.WriteString("data: {\"choices\":[{\"index\":0,\"delta\":{\"content\":\"partial\"}}]}\n\n")
	out := httptest.NewRecorder()
	_, err = bridge.Forward(out, &http.Response{Header: upstream.Header(), Body: upstream.Result().Body}, wireprotocol.NewCapture("openai-completions", true))
	if err == nil || !strings.Contains(out.Body.String(), "MODEL_GATEWAY_INTERRUPTED") || strings.Contains(out.Body.String(), "partial") {
		t.Fatalf("partial classifier accepted: %v %s", err, out.Body)
	}
}
