package protocol

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/modelgateway/protocoltest"
)

func TestGatewayPreservesMidTurnInstructionsNamespacesAndCustomToolContracts(t *testing.T) {
	q := protocoltest.Request("anthropic-messages", false)
	q["messages"] = append(arrayValue(q["messages"]), map[string]any{"role": "system", "content": []any{map[string]any{"type": "text", "text": "mid-turn-policy"}}})
	body, _ := json.Marshal(q)
	converted, _, err := prepareProtocolBridge(body, "anthropic-messages", "openai-completions", "fixture")
	if err != nil {
		t.Fatal(err)
	}
	var value map[string]any
	_ = json.Unmarshal(converted, &value)
	messages := arrayValue(value["messages"])
	if fieldText(objectValue(messages[len(messages)-1]), "role") != "system" || !strings.Contains(string(converted), "mid-turn-policy") {
		t.Fatal("mid-turn system instruction was moved or lost")
	}
	q = protocoltest.Request("openai-responses", false)
	q["tools"] = []any{map[string]any{"type": "namespace", "name": "client", "description": "Client file tools", "tools": []any{map[string]any{"type": "function", "name": "write_file", "description": "Write a file", "parameters": map[string]any{"type": "object"}}}}, map[string]any{"type": "web_search", "external_web_access": true}, map[string]any{"type": "custom", "name": "apply_patch", "description": "Apply a patch", "format": map[string]any{"type": "text"}}}
	body, _ = json.Marshal(q)
	converted, bridge, err := prepareProtocolBridge(body, "openai-responses", "openai-completions", "fixture")
	if err != nil {
		t.Fatal(err)
	}
	_ = json.Unmarshal(converted, &value)
	tools := arrayValue(value["tools"])
	if len(tools) != 2 || fieldText(objectValue(objectValue(tools[0])["function"]), "name") != "client__write_file" || len(bridge.request.DisabledTools) != 1 {
		t.Fatalf("namespaces or hosted-tool capability changed: %s", converted)
	}
	if !strings.Contains(string(converted), "does not provide provider-hosted tools") {
		t.Fatal("missing capability instruction")
	}
	w := httptest.NewRecorder()
	bridge.model = "coding-main"
	encoder := newProtocolEncoder(w, bridge)
	result := NewResult()
	result.Calls[0] = &protocolCall{"call_namespace", "client__write_file", "{}"}
	result.Calls[1] = &protocolCall{"call_custom", "apply_patch", "{\"input\":\"patch text\"}"}
	if err = encoder.finish(result, &Usage{100, 7, 20}); err != nil {
		t.Fatal(err)
	}
	var response map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &response)
	output := arrayValue(response["output"])
	if len(output) != 2 || fieldText(objectValue(output[0]), "namespace") != "client" || fieldText(objectValue(output[0]), "name") != "write_file" || fieldText(objectValue(output[1]), "type") != "custom_tool_call" || fieldText(objectValue(output[1]), "input") != "patch text" {
		t.Fatalf("client tool identity changed: %s", w.Body)
	}
	if w.Header().Get("X-Roami-Unsupported-Tools") != "web_search" {
		t.Fatal("hosted-tool limitation was hidden")
	}
	q["tool_choice"] = map[string]any{"type": "web_search"}
	body, _ = json.Marshal(q)
	if _, _, err = prepareProtocolBridge(body, "openai-responses", "openai-completions", "fixture"); err == nil {
		t.Fatal("forced unsupported hosted search was silently downgraded")
	}
}

func TestGatewayPreservesImagesAndReasoningInToolContinuations(t *testing.T) {
	request := map[string]any{"model": "coding-main", "input": []any{
		map[string]any{"type": "message", "role": "assistant", "content": []any{map[string]any{"type": "output_text", "text": "Checking"}}},
		map[string]any{"type": "reasoning", "summary": []any{map[string]any{"type": "summary_text", "text": "portable thought"}}},
		map[string]any{"type": "function_call", "name": "write_file", "call_id": "call_1", "arguments": "{}"},
		map[string]any{"type": "function_call_output", "call_id": "call_1", "output": "written"},
		map[string]any{"role": "user", "content": []any{map[string]any{"type": "input_image", "image_url": "data:image/png;base64,ZmFrZQ=="}}},
	}}
	body, _ := json.Marshal(request)
	converted, _, err := prepareProtocolBridge(body, "openai-responses", "openai-completions", "fixture")
	if err != nil {
		t.Fatal(err)
	}
	var raw map[string]any
	_ = json.Unmarshal(converted, &raw)
	messages := arrayValue(raw["messages"])
	assistant := objectValue(messages[0])
	if fieldText(assistant, "reasoning_content") != "portable thought" || len(arrayValue(assistant["tool_calls"])) != 1 || !strings.Contains(string(converted), "data:image/png;base64,ZmFrZQ==") {
		t.Fatalf("tool context or image lost: %s", converted)
	}
	request["input"] = []any{map[string]any{"type": "reasoning", "encrypted_content": "provider-bound"}}
	body, _ = json.Marshal(request)
	if _, _, err = prepareProtocolBridge(body, "openai-responses", "openai-completions", "fixture"); err == nil {
		t.Fatal("provider encrypted state was treated as portable text")
	}
}

func TestGatewayKeepsToolImagesAfterAllToolResultsAndPreservesStructuredOutputs(t *testing.T) {
	request := map[string]any{"model": "coding-main", "max_tokens": 128, "messages": []any{
		map[string]any{"role": "assistant", "content": []any{map[string]any{"type": "tool_use", "id": "image_call", "name": "read_image", "input": map[string]any{}}, map[string]any{"type": "tool_use", "id": "text_call", "name": "read_text", "input": map[string]any{}}}},
		map[string]any{"role": "user", "content": []any{map[string]any{"type": "tool_result", "tool_use_id": "image_call", "content": []any{map[string]any{"type": "image", "source": map[string]any{"type": "base64", "media_type": "image/png", "data": "ZmFrZQ=="}}}}, map[string]any{"type": "tool_result", "tool_use_id": "text_call", "content": "text-result"}}},
	}}
	body, _ := json.Marshal(request)
	converted, _, err := prepareProtocolBridge(body, "anthropic-messages", "openai-completions", "fixture")
	if err != nil {
		t.Fatal(err)
	}
	var raw map[string]any
	_ = json.Unmarshal(converted, &raw)
	messages := arrayValue(raw["messages"])
	if len(messages) != 4 || fieldText(objectValue(messages[1]), "role") != "tool" || fieldText(objectValue(messages[2]), "role") != "tool" || fieldText(objectValue(messages[3]), "role") != "user" {
		t.Fatalf("image insertion broke tool-result ordering: %s", converted)
	}
	if strings.Contains(string(mustJSON(objectValue(messages[1]))), "image_url") || !strings.Contains(string(mustJSON(objectValue(messages[3]))), "data:image/png;base64,ZmFrZQ==") {
		t.Fatal("image was lost or put in an invalid Chat tool message")
	}
	request = map[string]any{"model": "coding-main", "input": "hello", "text": map[string]any{"format": map[string]any{"type": "json_schema", "name": "answer", "schema": map[string]any{"type": "object", "properties": map[string]any{"answer": map[string]any{"type": "string"}}}, "strict": true}}}
	body, _ = json.Marshal(request)
	converted, _, err = prepareProtocolBridge(body, "openai-responses", "openai-completions", "fixture")
	if err != nil {
		t.Fatal(err)
	}
	_ = json.Unmarshal(converted, &raw)
	spec := objectValue(objectValue(raw["response_format"])["json_schema"])
	if spec["name"] != "answer" || spec["schema"] == nil || spec["strict"] != true || spec["type"] != nil {
		t.Fatalf("structured output changed: %s", converted)
	}
}

func mustJSON(value any) []byte { raw, _ := json.Marshal(value); return raw }

func TestGatewayStreamsCCThinkingBeforeFinalText(t *testing.T) {
	for _, stream := range []bool{false, true} {
		t.Run(fmt.Sprint(stream), func(t *testing.T) {
			bridge := &Bridge{from: "anthropic-messages", to: "openai-completions", model: "fixture", request: protocolRequest{Stream: true}}
			body := `{"choices":[{"message":{"role":"assistant","content":"GW_NATIVE_OK","reasoning_content":"Check first"},"finish_reason":"stop"}],"usage":{"prompt_tokens":100,"completion_tokens":7}}`
			contentType := "application/json"
			if stream {
				contentType = "text/event-stream"
				body = "data: {\"choices\":[{\"delta\":{\"content\":\"GW_NATIVE_OK\",\"reasoning_content\":\"Check first\"},\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":100,\"completion_tokens\":7}}\n\ndata: [DONE]\n\n"
			}
			response := &http.Response{Header: http.Header{"Content-Type": []string{contentType}}, Body: io.NopCloser(strings.NewReader(body))}
			capture := &Capture{protocol: "openai-completions", stream: stream}
			writer := httptest.NewRecorder()
			if _, err := bridge.Forward(writer, response, capture); err != nil {
				t.Fatal(err)
			}
			var blocks []string
			for _, line := range strings.Split(writer.Body.String(), "\n") {
				if !strings.HasPrefix(line, "data: ") {
					continue
				}
				var event map[string]any
				_ = json.Unmarshal([]byte(line[6:]), &event)
				if event["type"] == "content_block_start" {
					blocks = append(blocks, fieldText(objectValue(event["content_block"]), "type"))
				}
			}
			if strings.Join(blocks, ",") != "thinking,text" || !strings.Contains(writer.Body.String(), "GW_NATIVE_OK") || !strings.Contains(writer.Body.String(), "message_stop") {
				t.Fatalf("CC must receive final text after thinking: %v", blocks)
			}
		})
	}
}

func TestGatewayRejectsThinkingThatArrivesAfterCCText(t *testing.T) {
	w := httptest.NewRecorder()
	e := newProtocolEncoder(w, &Bridge{from: "anthropic-messages", request: protocolRequest{Stream: true}})
	if err := e.textWithReasoning("answer", ""); err != nil {
		t.Fatal(err)
	}
	r := NewResult()
	r.Text, r.Reasoning = "answer", "late thought"
	if err := e.finish(r, &Usage{100, 7, 0}); err == nil || strings.Contains(w.Body.String(), "message_stop") {
		t.Fatal("late reasoning must not replace a successful CC final reply")
	}
}

func TestGatewayDoesNotForceVendorThinkingDefaultsOnUnrelatedModels(t *testing.T) {
	for _, format := range []string{"anthropic-messages", "openai-responses"} {
		request := protocoltest.Request(format, true)
		if format == "anthropic-messages" {
			request["thinking"] = map[string]any{"type": "adaptive"}
			request["output_config"] = map[string]any{"effort": "high"}
		} else {
			request["reasoning"] = map[string]any{"effort": "high", "summary": "auto"}
		}
		body, _ := json.Marshal(request)
		converted, bridge, err := prepareProtocolBridge(body, format, "openai-completions", "fixture")
		if err != nil {
			t.Fatal(err)
		}
		var raw map[string]any
		_ = json.Unmarshal(converted, &raw)
		if raw["reasoning_effort"] != nil || raw["thinking"] != nil || raw["reasoning"] != nil {
			t.Fatal("provider-specific defaults were forced on the upstream")
		}
		writer := httptest.NewRecorder()
		_ = newProtocolEncoder(writer, bridge)
		if writer.Header().Get("X-Roami-Unsupported-Parameters") == "" {
			t.Fatal("unsupported vendor settings were hidden")
		}
	}
	request := protocoltest.Request("openai-completions", false)
	request["reasoning_effort"] = "low"
	body, _ := json.Marshal(request)
	converted, _, err := prepareProtocolBridge(body, "openai-completions", "openai-responses", "fixture")
	if err != nil {
		t.Fatal(err)
	}
	var raw map[string]any
	_ = json.Unmarshal(converted, &raw)
	if fieldText(objectValue(raw["reasoning"]), "effort") != "low" {
		t.Fatal("an explicitly saved Chat reasoning setting was lost")
	}
}
