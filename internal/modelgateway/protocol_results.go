package modelgateway

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"sort"
	"strings"
)

type protocolResult struct {
	reasoningBuffer       strings.Builder
	argumentBuffers       map[int]*strings.Builder
	textBuffer            strings.Builder
	Text, Reasoning, Stop string
	Calls                 map[int]*protocolCall
	Terminal              bool
	Size                  int
}

func newProtocolResult() *protocolResult {
	return &protocolResult{Stop: "stop", Calls: map[int]*protocolCall{}}
}
func (r *protocolResult) call(index int) *protocolCall {
	if r.Calls[index] == nil {
		r.Calls[index] = &protocolCall{}
	}
	return r.Calls[index]
}
func (r *protocolResult) calls() []protocolCall {
	keys := make([]int, 0, len(r.Calls))
	for key := range r.Calls {
		keys = append(keys, key)
	}
	sort.Ints(keys)
	calls := []protocolCall{}
	for _, key := range keys {
		calls = append(calls, *r.Calls[key])
	}
	return calls
}
func (r *protocolResult) text(text string, output func(string) error) error {
	r.Size += len(text)
	if r.Size > 32<<20 {
		return protocolFailure()
	}
	r.textBuffer.WriteString(text)
	r.Text = r.textBuffer.String()
	if text != "" {
		return output(text)
	}
	return nil
}
func (r *protocolResult) addReasoning(text string) {
	r.reasoningBuffer.WriteString(text)
	r.Reasoning = r.reasoningBuffer.String()
}
func (r *protocolResult) addArguments(index int, text string) {
	call := r.call(index)
	if r.argumentBuffers == nil {
		r.argumentBuffers = map[int]*strings.Builder{}
	}
	buffer := r.argumentBuffers[index]
	if buffer == nil {
		buffer = &strings.Builder{}
		buffer.WriteString(call.Arguments)
		r.argumentBuffers[index] = buffer
	}
	buffer.WriteString(text)
	call.Arguments = buffer.String()
}
func (r *protocolResult) event(raw []byte, format string, output func(string) error) error {
	if bytes.Equal(bytes.TrimSpace(raw), []byte("[DONE]")) {
		r.Terminal = true
		return nil
	}
	var event map[string]any
	if json.Unmarshal(raw, &event) != nil {
		return protocolFailure()
	}
	if event["error"] != nil || containsField([]string{"error", "response.failed", "response.incomplete"}, fieldText(event, "type")) {
		return errors.New("MODEL_GATEWAY_UPSTREAM_FAILED")
	}
	switch format {
	case "openai-completions":
		for _, value := range arrayValue(event["choices"]) {
			choice := objectValue(value)
			if index, ok := choice["index"].(float64); ok && index != 0 {
				return protocolFailure()
			}
			delta := objectValue(choice["delta"])
			if delta["content"] != nil {
				if _, ok := delta["content"].(string); !ok {
					return protocolFailure()
				}
			}
			r.addReasoning(fieldText(delta, "reasoning_content"))
			if e := r.text(fieldText(delta, "content"), output); e != nil {
				return e
			}
			for _, value := range arrayValue(delta["tool_calls"]) {
				row := objectValue(value)
				index, ok := row["index"].(float64)
				if !ok || index < 0 || index > 127 {
					return protocolFailure()
				}
				call := r.call(int(index))
				fn := objectValue(row["function"])
				call.ID += fieldText(row, "id")
				call.Name += fieldText(fn, "name")
				r.addArguments(int(index), fieldText(fn, "arguments"))
			}
			if stop := fieldText(choice, "finish_reason"); stop != "" {
				r.Stop = stop
			}
		}
	case "anthropic-messages":
		index, _ := event["index"].(float64)
		switch fieldText(event, "type") {
		case "content_block_start":
			block := objectValue(event["content_block"])
			switch fieldText(block, "type") {
			case "tool_use":
				if index < 0 || index > 127 {
					return protocolFailure()
				}
				call := r.call(int(index))
				call.ID = fieldText(block, "id")
				call.Name = fieldText(block, "name")
				if input := objectValue(block["input"]); len(input) > 0 {
					args, _ := json.Marshal(input)
					call.Arguments = string(args)
				}
			case "text":
				if e := r.text(fieldText(block, "text"), output); e != nil {
					return e
				}
			case "thinking":
				r.addReasoning(fieldText(block, "thinking"))
			default:
				return protocolFailure()
			}
		case "content_block_delta":
			delta := objectValue(event["delta"])
			switch fieldText(delta, "type") {
			case "text_delta":
				return r.text(fieldText(delta, "text"), output)
			case "input_json_delta":
				call := r.Calls[int(index)]
				if call == nil {
					return protocolFailure()
				}
				r.addArguments(int(index), fieldText(delta, "partial_json"))
			case "thinking_delta":
				r.addReasoning(fieldText(delta, "thinking"))
			case "signature_delta":
			default:
				return protocolFailure()
			}
		case "message_delta":
			if stop := fieldText(objectValue(event["delta"]), "stop_reason"); stop != "" {
				r.Stop = stop
			}
		case "message_stop":
			r.Terminal = true
		}
	case "openai-responses":
		index, _ := event["output_index"].(float64)
		switch fieldText(event, "type") {
		case "response.output_text.delta", "response.refusal.delta":
			return r.text(fieldText(event, "delta"), output)
		case "response.reasoning_summary_text.delta":
			r.addReasoning(fieldText(event, "delta"))
		case "response.output_item.added", "response.output_item.done":
			item := objectValue(event["item"])
			kind := fieldText(item, "type")
			if kind == "function_call" || kind == "custom_tool_call" {
				if index < 0 || index > 127 {
					return protocolFailure()
				}
				call := r.call(int(index))
				call.ID = fieldText(item, "call_id")
				call.Name = fieldText(item, "name")
				if args := fieldText(item, "arguments"); args != "" {
					call.Arguments = args
				}
				if kind == "custom_tool_call" {
					args, _ := json.Marshal(map[string]any{"input": item["input"]})
					call.Arguments = string(args)
				}
			}
		case "response.function_call_arguments.delta":
			r.addArguments(int(index), fieldText(event, "delta"))
		case "response.function_call_arguments.done":
			r.call(int(index)).Arguments = fieldText(event, "arguments")
		case "response.completed":
			final, e := decodeProtocolResult(objectValue(event["response"]), format)
			if e != nil {
				return e
			}
			if r.Text == "" {
				if e := r.text(final.Text, output); e != nil {
					return e
				}
			}
			if r.Reasoning == "" {
				r.Reasoning = final.Reasoning
			}
			for k, c := range final.Calls {
				r.Calls[k] = c
			}
			r.Stop = final.Stop
			r.Terminal = true
		}
	}
	size := len(r.Text) + len(r.Reasoning)
	for _, call := range r.Calls {
		size += len(call.ID) + len(call.Name) + len(call.Arguments)
	}
	if len(r.Calls) > 128 || size > 32<<20 {
		return protocolFailure()
	}
	return nil
}
func decodeProtocolResult(raw map[string]any, format string) (*protocolResult, error) {
	r := newProtocolResult()
	if raw == nil || raw["error"] != nil {
		return nil, protocolFailure()
	}
	switch format {
	case "openai-completions":
		choices := arrayValue(raw["choices"])
		if len(choices) != 1 {
			return nil, protocolFailure()
		}
		choice := objectValue(choices[0])
		m := objectValue(choice["message"])
		r.Stop = fieldText(choice, "finish_reason")
		parts, e := protocolContent(m["content"], format)
		if e != nil {
			return nil, e
		}
		r.Text, e = textBlocks(parts)
		if e != nil {
			return nil, e
		}
		r.Text += fieldText(m, "refusal")
		r.Reasoning = fieldText(m, "reasoning_content")
		for i, value := range arrayValue(m["tool_calls"]) {
			row := objectValue(value)
			fn := objectValue(row["function"])
			r.Calls[i] = &protocolCall{fieldText(row, "id"), fieldText(fn, "name"), fieldText(fn, "arguments")}
		}
	case "anthropic-messages":
		r.Stop = fieldText(raw, "stop_reason")
		for i, value := range arrayValue(raw["content"]) {
			row := objectValue(value)
			switch fieldText(row, "type") {
			case "text":
				r.textBuffer.WriteString(fieldText(row, "text"))
			case "thinking":
				r.addReasoning(fieldText(row, "thinking"))
			case "tool_use":
				args, _ := json.Marshal(row["input"])
				r.Calls[i] = &protocolCall{fieldText(row, "id"), fieldText(row, "name"), string(args)}
			default:
				return nil, protocolFailure()
			}
		}
	case "openai-responses":
		if fieldText(raw, "status") != "completed" {
			return nil, protocolFailure()
		}
		for i, value := range arrayValue(raw["output"]) {
			row := objectValue(value)
			switch fieldText(row, "type") {
			case "message":
				for _, value := range arrayValue(row["content"]) {
					part := objectValue(value)
					switch fieldText(part, "type") {
					case "output_text":
						r.textBuffer.WriteString(fieldText(part, "text"))
					case "refusal":
						r.textBuffer.WriteString(fieldText(part, "refusal"))
					default:
						return nil, protocolFailure()
					}
				}
			case "function_call":
				r.Calls[i] = &protocolCall{fieldText(row, "call_id"), fieldText(row, "name"), fieldText(row, "arguments")}
			case "custom_tool_call":
				args, _ := json.Marshal(map[string]any{"input": row["input"]})
				r.Calls[i] = &protocolCall{fieldText(row, "call_id"), fieldText(row, "name"), string(args)}
			case "reasoning":
				for _, value := range arrayValue(row["summary"]) {
					r.addReasoning(fieldText(objectValue(value), "text"))
				}
			default:
				return nil, protocolFailure()
			}
		}
	}
	if r.textBuffer.Len() > 0 {
		r.Text = r.textBuffer.String()
	}
	return r, nil
}

type protocolCaptureReader struct {
	io.Reader
	capture *nativeUsageCapture
}

func (r protocolCaptureReader) Read(p []byte) (int, error) {
	n, e := r.Reader.Read(p)
	if n > 0 {
		r.capture.feed(p[:n])
	}
	return n, e
}
func (b *protocolBridge) forward(w http.ResponseWriter, response *http.Response, capture *nativeUsageCapture) (complete bool, failure error) {
	result := newProtocolResult()
	encoder := newProtocolEncoder(w, b)
	defer func() {
		if failure != nil {
			encoder.fail(protocolCode(failure))
		}
	}()
	reader := protocolCaptureReader{Reader: response.Body, capture: capture}
	if capture.stream {
		scanner := bufio.NewScanner(reader)
		scanner.Buffer(make([]byte, 32<<10), 4<<20)
		var data []string
		total := 0
		dispatch := func() error {
			if len(data) == 0 {
				return nil
			}
			e := result.event([]byte(strings.Join(data, "\n")), b.to, func(text string) error {
				return encoder.textWithReasoning(text, result.Reasoning)
			})
			data = nil
			return e
		}
		for scanner.Scan() {
			line := scanner.Text()
			total += len(line)
			if total > 64<<20 {
				encoder.fail("MODEL_GATEWAY_CONTENT_UNSUPPORTED")
				return false, protocolFailure()
			}
			if line == "" {
				if e := dispatch(); e != nil {
					encoder.fail(protocolCode(e))
					return false, e
				}
				if result.Terminal {
					break
				}
			} else if strings.HasPrefix(line, "data:") {
				data = append(data, strings.TrimSpace(line[5:]))
			}
		}
		if scanner.Err() != nil {
			encoder.fail("MODEL_GATEWAY_INTERRUPTED")
			return false, scanner.Err()
		}
		if e := dispatch(); e != nil {
			encoder.fail(protocolCode(e))
			return true, e
		}
		if !result.Terminal {
			encoder.fail("MODEL_GATEWAY_INTERRUPTED")
			return true, errors.New("MODEL_GATEWAY_INTERRUPTED")
		}
	} else {
		raw, e := io.ReadAll(io.LimitReader(reader, (32<<20)+1))
		if e != nil {
			return false, e
		}
		if len(raw) > 32<<20 {
			return false, protocolFailure()
		}
		var value map[string]any
		if json.Unmarshal(raw, &value) != nil {
			return true, protocolFailure()
		}
		result, e = decodeProtocolResult(value, b.to)
		if e != nil {
			return true, e
		}
		if e = encoder.textWithReasoning(result.Text, result.Reasoning); e != nil {
			return true, e
		}
	}
	usage := capture.finish(true)
	if usage == nil {
		encoder.fail("MODEL_PROXY_USAGE_UNKNOWN")
		return true, errors.New("MODEL_PROXY_USAGE_UNKNOWN")
	}
	if e := encoder.finish(result, usage); e != nil {
		encoder.fail(protocolCode(e))
		return true, e
	}
	return true, nil
}
