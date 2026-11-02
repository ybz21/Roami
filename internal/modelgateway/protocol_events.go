package modelgateway

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"
)

type protocolEncoder struct {
	writer                      http.ResponseWriter
	bridge                      *protocolBridge
	id, messageID               string
	sequence                    int
	started, failed, textOpened bool
	textIndex                   int
	thinkingPrefix              string
}

func newProtocolEncoder(w http.ResponseWriter, b *protocolBridge) *protocolEncoder {
	id, _ := randomCatalogID()
	if len(b.request.DisabledTools) > 0 {
		w.Header().Set("X-Roami-Unsupported-Tools", strings.Join(b.request.DisabledTools, ","))
	}
	if len(b.request.IgnoredParameters) > 0 {
		w.Header().Set("X-Roami-Unsupported-Parameters", strings.Join(b.request.IgnoredParameters, ","))
	}
	return &protocolEncoder{writer: w, bridge: b, id: "resp_" + id, messageID: "msg_" + id}
}
func protocolCode(e error) string {
	if strings.HasPrefix(e.Error(), "MODEL_") {
		return e.Error()
	}
	return "MODEL_GATEWAY_INTERRUPTED"
}
func (e *protocolEncoder) event(kind string, value map[string]any) error {
	if e.bridge.from == "openai-responses" {
		value["sequence_number"] = e.sequence
		e.sequence++
	}
	raw, err := json.Marshal(value)
	if err != nil {
		return err
	}
	if kind != "" {
		if _, err = fmt.Fprintf(e.writer, "event: %s\n", kind); err != nil {
			return err
		}
	}
	_, err = fmt.Fprintf(e.writer, "data: %s\n\n", raw)
	if f, ok := e.writer.(http.Flusher); ok {
		f.Flush()
	}
	return err
}
func (e *protocolEncoder) response(status string, output []any, usage any) map[string]any {
	return map[string]any{"id": e.id, "object": "response", "created_at": time.Now().Unix(), "status": status, "model": e.bridge.model, "output": output, "error": nil, "incomplete_details": nil, "parallel_tool_calls": true, "usage": usage}
}
func protocolUsage(u *Usage, format string) map[string]any {
	switch format {
	case "anthropic-messages":
		return map[string]any{"input_tokens": u.Input - u.Cached, "output_tokens": u.Output, "cache_read_input_tokens": u.Cached, "cache_creation_input_tokens": 0}
	case "openai-responses":
		return map[string]any{"input_tokens": u.Input, "output_tokens": u.Output, "total_tokens": u.Input + u.Output, "input_tokens_details": map[string]any{"cached_tokens": u.Cached}, "output_tokens_details": map[string]any{"reasoning_tokens": 0}}
	default:
		return map[string]any{"prompt_tokens": u.Input, "completion_tokens": u.Output, "total_tokens": u.Input + u.Output, "prompt_tokens_details": map[string]any{"cached_tokens": u.Cached}}
	}
}
func (e *protocolEncoder) start() error {
	if e.started {
		return nil
	}
	e.started = true
	e.writer.Header().Set("Content-Type", "text/event-stream")
	e.writer.Header().Set("Cache-Control", "no-cache")
	switch e.bridge.from {
	case "anthropic-messages":
		return e.event("message_start", map[string]any{"type": "message_start", "message": map[string]any{"id": e.messageID, "type": "message", "role": "assistant", "model": e.bridge.model, "content": []any{}, "stop_reason": nil, "stop_sequence": nil, "usage": protocolUsage(&Usage{}, "anthropic-messages")}})
	case "openai-responses":
		response := e.response("in_progress", []any{}, nil)
		if err := e.event("response.created", map[string]any{"type": "response.created", "response": response}); err != nil {
			return err
		}
		return e.event("response.in_progress", map[string]any{"type": "response.in_progress", "response": response})
	default:
		return e.chatChunk(map[string]any{"role": "assistant"}, nil, nil)
	}
}
func (e *protocolEncoder) chatChunk(delta any, stop any, usage any) error {
	choices := []any{map[string]any{"index": 0, "delta": delta, "finish_reason": stop}}
	if delta == nil {
		choices = []any{}
	}
	value := map[string]any{"id": e.id, "object": "chat.completion.chunk", "created": time.Now().Unix(), "model": e.bridge.model, "choices": choices}
	if usage != nil {
		value["usage"] = usage
	}
	return e.event("", value)
}
func outputText(text string) map[string]any {
	return map[string]any{"type": "output_text", "text": text, "annotations": []any{}, "logprobs": []any{}}
}
func (e *protocolEncoder) message(text, status string) map[string]any {
	return map[string]any{"id": e.messageID, "type": "message", "role": "assistant", "status": status, "content": []any{outputText(text)}}
}
func (e *protocolEncoder) thinking(index int, text string) error {
	if err := e.event("content_block_start", map[string]any{"type": "content_block_start", "index": index, "content_block": map[string]any{"type": "thinking", "thinking": "", "signature": ""}}); err != nil {
		return err
	}
	if err := e.event("content_block_delta", map[string]any{"type": "content_block_delta", "index": index, "delta": map[string]any{"type": "thinking_delta", "thinking": text}}); err != nil {
		return err
	}
	return e.event("content_block_stop", map[string]any{"type": "content_block_stop", "index": index})
}
func (e *protocolEncoder) textWithReasoning(text, reasoning string) error {
	if text == "" {
		return nil
	}
	if e.bridge.request.Stream && e.bridge.from == "anthropic-messages" && !e.textOpened && reasoning != "" && text != "" {
		if err := e.start(); err != nil {
			return err
		}
		if err := e.thinking(0, reasoning); err != nil {
			return err
		}
		e.thinkingPrefix = reasoning
		e.textIndex = 1
	}
	return e.text(text)
}
func (e *protocolEncoder) text(text string) error {
	if !e.bridge.request.Stream {
		return nil
	}
	if err := e.start(); err != nil {
		return err
	}
	if !e.textOpened {
		e.textOpened = true
		switch e.bridge.from {
		case "anthropic-messages":
			if err := e.event("content_block_start", map[string]any{"type": "content_block_start", "index": e.textIndex, "content_block": map[string]any{"type": "text", "text": ""}}); err != nil {
				return err
			}
		case "openai-responses":
			item := e.message("", "in_progress")
			item["content"] = []any{}
			if err := e.event("response.output_item.added", map[string]any{"type": "response.output_item.added", "output_index": 0, "item": item}); err != nil {
				return err
			}
			if err := e.event("response.content_part.added", map[string]any{"type": "response.content_part.added", "item_id": e.messageID, "output_index": 0, "content_index": 0, "part": outputText("")}); err != nil {
				return err
			}
		}
	}
	switch e.bridge.from {
	case "anthropic-messages":
		return e.event("content_block_delta", map[string]any{"type": "content_block_delta", "index": e.textIndex, "delta": map[string]any{"type": "text_delta", "text": text}})
	case "openai-responses":
		return e.event("response.output_text.delta", map[string]any{"type": "response.output_text.delta", "item_id": e.messageID, "output_index": 0, "content_index": 0, "delta": text, "logprobs": []any{}})
	default:
		return e.chatChunk(map[string]any{"content": text}, nil, nil)
	}
}
func (e *protocolEncoder) custom(name string) bool {
	for _, t := range e.bridge.request.Tools {
		if t.Name == name {
			return t.Custom
		}
	}
	return false
}
func (e *protocolEncoder) responseTool(call protocolCall, index int) (map[string]any, error) {
	item := map[string]any{"id": fmt.Sprintf("%s_tool_%d", e.id, index), "type": "function_call", "status": "completed", "call_id": call.ID, "name": call.Name, "arguments": call.Arguments}
	for _, tool := range e.bridge.request.Tools {
		if tool.Name == call.Name && tool.Namespace != "" {
			item["namespace"] = tool.Namespace
			item["name"] = tool.OriginalName
		}
	}
	if e.custom(call.Name) {
		var args map[string]any
		if json.Unmarshal([]byte(call.Arguments), &args) != nil {
			return nil, protocolFailure()
		}
		input, ok := args["input"].(string)
		if !ok {
			return nil, protocolFailure()
		}
		delete(item, "arguments")
		item["type"] = "custom_tool_call"
		item["input"] = input
	}
	return item, nil
}
func protocolStop(r *protocolResult) string {
	if len(r.Calls) > 0 {
		return "tool_calls"
	}
	if r.Stop == "length" || r.Stop == "max_tokens" {
		return "length"
	}
	return "stop"
}
func (e *protocolEncoder) finish(r *protocolResult, u *Usage) error {
	if len(e.bridge.request.DisabledTools) > 0 {
		e.writer.Header().Set("X-Roami-Unsupported-Tools", strings.Join(e.bridge.request.DisabledTools, ","))
	}
	calls := r.calls()
	for i := range calls {
		call := &calls[i]
		allowed := false
		for _, tool := range e.bridge.request.Tools {
			if tool.Name == call.Name {
				allowed = true
			}
		}
		if !allowed {
			return protocolFailure()
		}

		if call.Arguments == "" {
			call.Arguments = "{}"
		}
		var args map[string]any
		if call.ID == "" || call.Name == "" || json.Unmarshal([]byte(call.Arguments), &args) != nil || args == nil {
			return protocolFailure()
		}
	}
	usage := protocolUsage(u, e.bridge.from)
	stop := protocolStop(r)
	if !e.bridge.request.Stream {
		e.writer.Header().Set("Content-Type", "application/json")
		switch e.bridge.from {
		case "anthropic-messages":
			content := []any{}
			if r.Reasoning != "" {
				content = append(content, map[string]any{"type": "thinking", "thinking": r.Reasoning, "signature": ""})
			}
			if r.Text != "" || len(calls) == 0 {
				content = append(content, map[string]any{"type": "text", "text": r.Text})
			}
			for _, call := range calls {
				var input any
				_ = json.Unmarshal([]byte(call.Arguments), &input)
				content = append(content, map[string]any{"type": "tool_use", "id": call.ID, "name": call.Name, "input": input})
			}
			reason := "end_turn"
			if stop == "length" {
				reason = "max_tokens"
			}
			if stop == "tool_calls" {
				reason = "tool_use"
			}
			return json.NewEncoder(e.writer).Encode(map[string]any{"id": e.messageID, "type": "message", "role": "assistant", "model": e.bridge.model, "content": content, "stop_reason": reason, "stop_sequence": nil, "usage": usage})
		case "openai-responses":
			output := []any{}
			if r.Text != "" || len(calls) == 0 {
				output = append(output, e.message(r.Text, "completed"))
			}
			if r.Reasoning != "" {
				output = append(output, map[string]any{"id": e.id + "_reasoning", "type": "reasoning", "summary": []any{map[string]any{"type": "summary_text", "text": r.Reasoning}}})
			}
			for i, call := range calls {
				item, err := e.responseTool(call, i)
				if err != nil {
					return err
				}
				output = append(output, item)
			}
			response := e.response("completed", output, usage)
			if stop == "length" {
				response["status"] = "incomplete"
				response["incomplete_details"] = map[string]any{"reason": "max_output_tokens"}
			}
			return json.NewEncoder(e.writer).Encode(response)
		default:
			message := map[string]any{"role": "assistant", "content": r.Text}
			if r.Reasoning != "" {
				message["reasoning_content"] = r.Reasoning
			}
			tools := []any{}
			for _, call := range calls {
				tools = append(tools, map[string]any{"id": call.ID, "type": "function", "function": map[string]any{"name": call.Name, "arguments": call.Arguments}})
			}
			if len(tools) > 0 {
				message["tool_calls"] = tools
			}
			return json.NewEncoder(e.writer).Encode(map[string]any{"id": e.id, "object": "chat.completion", "created": time.Now().Unix(), "model": e.bridge.model, "choices": []any{map[string]any{"index": 0, "message": message, "finish_reason": stop}}, "usage": usage})
		}
	}
	if err := e.start(); err != nil {
		return err
	}
	if r.Text == "" && r.Reasoning == "" && len(calls) == 0 && !e.textOpened {
		if err := e.text(""); err != nil {
			return err
		}
	}
	switch e.bridge.from {
	case "anthropic-messages":
		index := e.textIndex
		if e.textOpened && r.Reasoning != e.thinkingPrefix {
			return protocolFailure()
		}
		if e.textOpened {
			if err := e.event("content_block_stop", map[string]any{"type": "content_block_stop", "index": index}); err != nil {
				return err
			}
			index++
		}
		if r.Reasoning != "" && !e.textOpened {
			if err := e.thinking(index, r.Reasoning); err != nil {
				return err
			}
			index++
		}
		for _, call := range calls {
			if err := e.event("content_block_start", map[string]any{"type": "content_block_start", "index": index, "content_block": map[string]any{"type": "tool_use", "id": call.ID, "name": call.Name, "input": map[string]any{}}}); err != nil {
				return err
			}
			if err := e.event("content_block_delta", map[string]any{"type": "content_block_delta", "index": index, "delta": map[string]any{"type": "input_json_delta", "partial_json": call.Arguments}}); err != nil {
				return err
			}
			if err := e.event("content_block_stop", map[string]any{"type": "content_block_stop", "index": index}); err != nil {
				return err
			}
			index++
		}
		reason := "end_turn"
		if stop == "length" {
			reason = "max_tokens"
		}
		if stop == "tool_calls" {
			reason = "tool_use"
		}
		if err := e.event("message_delta", map[string]any{"type": "message_delta", "delta": map[string]any{"stop_reason": reason, "stop_sequence": nil}, "usage": usage}); err != nil {
			return err
		}
		return e.event("message_stop", map[string]any{"type": "message_stop"})
	case "openai-responses":
		output := []any{}
		index := 0
		if e.textOpened {
			if err := e.event("response.output_text.done", map[string]any{"type": "response.output_text.done", "item_id": e.messageID, "output_index": 0, "content_index": 0, "text": r.Text, "logprobs": []any{}}); err != nil {
				return err
			}
			if err := e.event("response.content_part.done", map[string]any{"type": "response.content_part.done", "item_id": e.messageID, "output_index": 0, "content_index": 0, "part": outputText(r.Text)}); err != nil {
				return err
			}
			item := e.message(r.Text, "completed")
			if err := e.event("response.output_item.done", map[string]any{"type": "response.output_item.done", "output_index": 0, "item": item}); err != nil {
				return err
			}
			output = append(output, item)
			index++
		}
		if r.Reasoning != "" {
			item := map[string]any{"id": e.id + "_reasoning", "type": "reasoning", "summary": []any{map[string]any{"type": "summary_text", "text": r.Reasoning}}}
			if err := e.event("response.output_item.added", map[string]any{"type": "response.output_item.added", "output_index": index, "item": item}); err != nil {
				return err
			}
			if err := e.event("response.output_item.done", map[string]any{"type": "response.output_item.done", "output_index": index, "item": item}); err != nil {
				return err
			}
			output = append(output, item)
			index++
		}
		for _, call := range calls {
			item, err := e.responseTool(call, index)
			if err != nil {
				return err
			}
			pending := map[string]any{}
			for k, v := range item {
				pending[k] = v
			}
			pending["status"] = "in_progress"
			custom := fieldText(item, "type") == "custom_tool_call"
			field := "arguments"
			event := "response.function_call_arguments"
			if custom {
				field = "input"
				event = "response.custom_tool_call_input"
			}
			pending[field] = ""
			if err = e.event("response.output_item.added", map[string]any{"type": "response.output_item.added", "output_index": index, "item": pending}); err != nil {
				return err
			}
			if err = e.event(event+".delta", map[string]any{"type": event + ".delta", "output_index": index, "item_id": item["id"], "delta": item[field]}); err != nil {
				return err
			}
			if err = e.event(event+".done", map[string]any{"type": event + ".done", "output_index": index, "item_id": item["id"], field: item[field]}); err != nil {
				return err
			}
			if err = e.event("response.output_item.done", map[string]any{"type": "response.output_item.done", "output_index": index, "item": item}); err != nil {
				return err
			}
			output = append(output, item)
			index++
		}
		response := e.response("completed", output, usage)
		kind := "response.completed"
		if stop == "length" {
			response["status"] = "incomplete"
			response["incomplete_details"] = map[string]any{"reason": "max_output_tokens"}
			kind = "response.incomplete"
		}
		return e.event(kind, map[string]any{"type": kind, "response": response})
	default:
		if r.Reasoning != "" {
			if err := e.chatChunk(map[string]any{"reasoning_content": r.Reasoning}, nil, nil); err != nil {
				return err
			}
		}
		for i, call := range calls {
			if err := e.chatChunk(map[string]any{"tool_calls": []any{map[string]any{"index": i, "id": call.ID, "type": "function", "function": map[string]any{"name": call.Name, "arguments": call.Arguments}}}}, nil, nil); err != nil {
				return err
			}
		}
		if err := e.chatChunk(map[string]any{}, stop, nil); err != nil {
			return err
		}
		if err := e.chatChunk(nil, nil, usage); err != nil {
			return err
		}
		_, err := fmt.Fprint(e.writer, "data: [DONE]\n\n")
		if f, ok := e.writer.(http.Flusher); ok {
			f.Flush()
		}
		return err
	}
}
func (e *protocolEncoder) fail(code string) {
	e.failStatus(code, http.StatusBadGateway)
}
func (e *protocolEncoder) failStatus(code string, status int) {
	if e.failed {
		return
	}
	e.failed = true
	if !strings.HasPrefix(code, "MODEL_") {
		code = "MODEL_GATEWAY_INTERRUPTED"
	}
	errorValue := map[string]any{"type": "api_error", "code": code, "message": code}
	if !e.started {
		writeJSON(e.writer, status, map[string]any{"type": "error", "error": errorValue})
		return
	}
	if e.bridge.from == "openai-responses" {
		response := e.response("failed", []any{}, nil)
		response["error"] = errorValue
		_ = e.event("response.failed", map[string]any{"type": "response.failed", "response": response})
	} else if e.bridge.from == "anthropic-messages" {
		_ = e.event("error", map[string]any{"type": "error", "error": errorValue})
	} else {
		_ = e.event("", map[string]any{"error": errorValue})
	}
}
