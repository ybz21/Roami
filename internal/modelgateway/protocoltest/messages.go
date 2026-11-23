// Package protocoltest supplies wire fixtures for gateway and protocol tests.
package protocoltest

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

func Request(format string, stream bool) map[string]any {
	schema := map[string]any{"type": "object", "properties": map[string]any{"path": map[string]any{"type": "string"}}, "required": []string{"path"}}
	out := map[string]any{"model": "coding-main", "stream": stream}
	switch format {
	case "openai-completions":
		out["messages"] = []any{map[string]any{"role": "system", "content": "policy"}, map[string]any{"role": "assistant", "content": nil, "tool_calls": []any{map[string]any{"id": "call_prior", "type": "function", "function": map[string]any{"name": "write_file", "arguments": "{\"path\":\"before\"}"}}}}, map[string]any{"role": "tool", "tool_call_id": "call_prior", "content": "prior-result"}, map[string]any{"role": "user", "content": "next"}}
		out["tools"] = []any{map[string]any{"type": "function", "function": map[string]any{"name": "write_file", "parameters": schema}}}
	case "anthropic-messages":
		out["system"] = "policy"
		out["max_tokens"] = 128
		out["messages"] = []any{map[string]any{"role": "assistant", "content": []any{map[string]any{"type": "tool_use", "id": "call_prior", "name": "write_file", "input": map[string]any{"path": "before"}}}}, map[string]any{"role": "user", "content": []any{map[string]any{"type": "tool_result", "tool_use_id": "call_prior", "content": "prior-result"}, map[string]any{"type": "text", "text": "next"}}}}
		out["tools"] = []any{map[string]any{"name": "write_file", "input_schema": schema}}
	case "openai-responses":
		out["instructions"] = "policy"
		out["input"] = []any{map[string]any{"type": "function_call", "call_id": "call_prior", "name": "write_file", "arguments": "{\"path\":\"before\"}"}, map[string]any{"type": "function_call_output", "call_id": "call_prior", "output": "prior-result"}, map[string]any{"type": "message", "role": "user", "content": []any{map[string]any{"type": "input_text", "text": "next"}}}}
		out["tools"] = []any{map[string]any{"type": "function", "name": "write_file", "parameters": schema}}
	}
	return out
}
func fixtureProtocolUsage(format string) map[string]any {
	switch format {
	case "anthropic-messages":
		return map[string]any{"input_tokens": 80, "output_tokens": 7, "cache_read_input_tokens": 20}
	case "openai-responses":
		return map[string]any{"input_tokens": 100, "output_tokens": 7, "input_tokens_details": map[string]any{"cached_tokens": 20}}
	default:
		return map[string]any{"prompt_tokens": 100, "completion_tokens": 7, "prompt_tokens_details": map[string]any{"cached_tokens": 20}}
	}
}
func Response(format string) map[string]any {
	usage := fixtureProtocolUsage(format)
	switch format {
	case "anthropic-messages":
		return map[string]any{"id": "msg_fixture", "type": "message", "role": "assistant", "model": "fixture", "content": []any{map[string]any{"type": "text", "text": "Ready"}, map[string]any{"type": "tool_use", "id": "call_write", "name": "write_file", "input": map[string]any{"path": "out.txt"}}}, "stop_reason": "tool_use", "usage": usage}
	case "openai-responses":
		return map[string]any{"id": "resp_fixture", "status": "completed", "output": []any{map[string]any{"type": "message", "role": "assistant", "content": []any{map[string]any{"type": "output_text", "text": "Ready"}}}, map[string]any{"type": "function_call", "call_id": "call_write", "name": "write_file", "arguments": "{\"path\":\"out.txt\"}"}}, "usage": usage}
	default:
		return map[string]any{"id": "chat_fixture", "choices": []any{map[string]any{"index": 0, "message": map[string]any{"role": "assistant", "content": "Ready", "tool_calls": []any{map[string]any{"type": "function", "id": "call_write", "function": map[string]any{"name": "write_file", "arguments": "{\"path\":\"out.txt\"}"}}}}, "finish_reason": "tool_calls"}}, "usage": usage}
	}
}
func WriteResponse(w http.ResponseWriter, format string, stream bool) {
	if !stream {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(Response(format))
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	send := func(value map[string]any) {
		raw, _ := json.Marshal(value)
		if kind, _ := value["type"].(string); kind != "" {
			_, _ = fmt.Fprintf(w, "event: %s\n", kind)
		}
		_, _ = fmt.Fprintf(w, "data: %s\n\n", raw)
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}
	}
	switch format {
	case "openai-completions":
		send(map[string]any{"choices": []any{map[string]any{"index": 0, "delta": map[string]any{"content": "Ready"}}}})
		send(map[string]any{"choices": []any{map[string]any{"index": 0, "delta": map[string]any{"tool_calls": []any{map[string]any{"index": 0, "id": "call_write", "type": "function", "function": map[string]any{"name": "write_file", "arguments": "{\"path\":"}}}}}}})
		send(map[string]any{"choices": []any{map[string]any{"index": 0, "delta": map[string]any{"tool_calls": []any{map[string]any{"index": 0, "function": map[string]any{"arguments": "\"out.txt\"}"}}}}, "finish_reason": "tool_calls"}}})
		send(map[string]any{"choices": []any{}, "usage": fixtureProtocolUsage(format)})
		_, _ = io.WriteString(w, "data: [DONE]\n\n")
	case "anthropic-messages":
		send(map[string]any{"type": "message_start", "message": map[string]any{"usage": map[string]any{"input_tokens": 80, "output_tokens": 0, "cache_read_input_tokens": 20}}})
		send(map[string]any{"type": "content_block_start", "index": 0, "content_block": map[string]any{"type": "text", "text": ""}})
		send(map[string]any{"type": "content_block_delta", "index": 0, "delta": map[string]any{"type": "text_delta", "text": "Ready"}})
		send(map[string]any{"type": "content_block_stop", "index": 0})
		send(map[string]any{"type": "content_block_start", "index": 1, "content_block": map[string]any{"type": "tool_use", "id": "call_write", "name": "write_file", "input": map[string]any{}}})
		send(map[string]any{"type": "content_block_delta", "index": 1, "delta": map[string]any{"type": "input_json_delta", "partial_json": "{\"path\":\"out.txt\"}"}})
		send(map[string]any{"type": "content_block_stop", "index": 1})
		send(map[string]any{"type": "message_delta", "delta": map[string]any{"stop_reason": "tool_use"}, "usage": map[string]any{"output_tokens": 7}})
		send(map[string]any{"type": "message_stop"})
	case "openai-responses":
		send(map[string]any{"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": "Ready"})
		send(map[string]any{"type": "response.output_item.added", "output_index": 1, "item": map[string]any{"type": "function_call", "id": "fc_fixture", "call_id": "call_write", "name": "write_file", "arguments": ""}})
		send(map[string]any{"type": "response.function_call_arguments.delta", "output_index": 1, "delta": "{\"path\":\"out.txt\"}"})
		send(map[string]any{"type": "response.completed", "response": Response(format)})
	}
}
