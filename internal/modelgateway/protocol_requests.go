package modelgateway

import (
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

type protocolBlock struct{ Kind, Text, URL string }
type protocolCall struct{ ID, Name, Arguments string }
type protocolMessage struct {
	Role, CallID, Reasoning string
	Content                 []protocolBlock
	Calls                   []protocolCall
}
type protocolTool struct {
	Name, Description       string
	Namespace, OriginalName string
	Schema                  any
	Custom                  bool
}
type protocolRequest struct {
	DisabledTools     []string
	IgnoredParameters []string
	Messages          []protocolMessage
	Tools             []protocolTool
	Params            map[string]any
	Choice, NamedTool string
	Parallel          *bool
	Stream            bool
}
type protocolBridge struct {
	from, to, model string
	request         protocolRequest
}

func protocolFailure() error                      { return errors.New("MODEL_GATEWAY_CONTENT_UNSUPPORTED") }
func objectValue(v any) map[string]any            { m, _ := v.(map[string]any); return m }
func arrayValue(v any) []any                      { a, _ := v.([]any); return a }
func textValue(v any) string                      { s, _ := v.(string); return s }
func fieldText(m map[string]any, k string) string { return textValue(m[k]) }

func protocolContent(v any, format string) ([]protocolBlock, error) {
	if v == nil {
		return nil, nil
	}
	if text, ok := v.(string); ok {
		return []protocolBlock{{Kind: "text", Text: text}}, nil
	}
	parts, ok := v.([]any)
	if !ok {
		return nil, protocolFailure()
	}
	var result []protocolBlock
	for _, part := range parts {
		p := objectValue(part)
		switch fieldText(p, "type") {
		case "text", "input_text", "output_text":
			result = append(result, protocolBlock{Kind: "text", Text: fieldText(p, "text")})
		case "tool_reference":
			result = append(result, protocolBlock{Kind: "text", Text: "Available tool: " + fieldText(p, "tool_name")})
		case "image_url":
			url := fieldText(objectValue(p["image_url"]), "url")
			if url == "" {
				return nil, protocolFailure()
			}
			result = append(result, protocolBlock{Kind: "image", URL: url})
		case "input_image":
			url := fieldText(p, "image_url")
			if url == "" {
				return nil, protocolFailure()
			}
			result = append(result, protocolBlock{Kind: "image", URL: url})
		case "image":
			source := objectValue(p["source"])
			url := fieldText(source, "url")
			if fieldText(source, "type") == "base64" {
				url = "data:" + fieldText(source, "media_type") + ";base64," + fieldText(source, "data")
			}
			if url == "" {
				return nil, protocolFailure()
			}
			result = append(result, protocolBlock{Kind: "image", URL: url})
		default:
			return nil, protocolFailure()
		}
	}
	return result, nil
}
func textBlocks(parts []protocolBlock) (string, error) {
	var b strings.Builder
	for _, p := range parts {
		if p.Kind != "text" {
			return "", protocolFailure()
		}
		b.WriteString(p.Text)
	}
	return b.String(), nil
}
func decodeProtocolRequest(body []byte, format string) (protocolRequest, error) {
	var raw map[string]any
	if json.Unmarshal(body, &raw) != nil {
		return protocolRequest{}, protocolFailure()
	}
	q := protocolRequest{Params: map[string]any{}}
	q.Stream, _ = raw["stream"].(bool)
	if raw["stream"] != nil {
		if _, ok := raw["stream"].(bool); !ok {
			return q, protocolFailure()
		}
	}
	if raw["tools"] != nil {
		if _, ok := raw["tools"].([]any); !ok {
			return q, protocolFailure()
		}
	}
	for _, key := range []string{"temperature", "top_p", "max_tokens", "max_completion_tokens", "max_output_tokens", "stop", "stop_sequences", "reasoning_effort"} {
		if v, ok := raw[key]; ok && v != nil {
			q.Params[key] = v
		}
	}
	if n, ok := raw["n"].(float64); ok && n != 1 {
		return q, protocolFailure()
	}
	if raw["conversation"] != nil || raw["previous_response_id"] != nil {
		return q, protocolFailure()
	}
	if format == "openai-responses" && raw["reasoning"] != nil {
		q.IgnoredParameters = append(q.IgnoredParameters, "reasoning")
	}
	if format == "anthropic-messages" {
		if raw["thinking"] != nil {
			q.IgnoredParameters = append(q.IgnoredParameters, "thinking")
		}
		if objectValue(raw["output_config"])["effort"] != nil {
			q.IgnoredParameters = append(q.IgnoredParameters, "output_config.effort")
		}
	}
	if format == "openai-completions" && raw["response_format"] != nil {
		q.Params["response_format"] = raw["response_format"]
	}
	if format == "openai-responses" {
		if f := objectValue(raw["text"])["format"]; f != nil {
			q.Params["response_format"] = f
		}
	}
	if format == "anthropic-messages" {
		if f := objectValue(raw["output_config"])["format"]; f != nil {
			q.Params["response_format"] = f
		}
	}
	if p, ok := raw["parallel_tool_calls"].(bool); ok {
		q.Parallel = &p
	}
	add := func(role string, content any) error {
		parts, e := protocolContent(content, format)
		if e != nil {
			return e
		}
		if role == "developer" {
			role = "system"
		}
		if !containsField([]string{"system", "user", "assistant", "tool"}, role) {
			return protocolFailure()
		}
		q.Messages = append(q.Messages, protocolMessage{Role: role, Content: parts})
		return nil
	}
	switch format {
	case "openai-completions":
		for _, value := range arrayValue(raw["messages"]) {
			m := objectValue(value)
			if e := add(fieldText(m, "role"), m["content"]); e != nil {
				return q, e
			}
			msg := &q.Messages[len(q.Messages)-1]
			msg.CallID = fieldText(m, "tool_call_id")
			msg.Reasoning = fieldText(m, "reasoning_content")
			for _, value := range arrayValue(m["tool_calls"]) {
				call := objectValue(value)
				f := objectValue(call["function"])
				if fieldText(call, "type") != "function" {
					return q, protocolFailure()
				}
				msg.Calls = append(msg.Calls, protocolCall{fieldText(call, "id"), fieldText(f, "name"), fieldText(f, "arguments")})
			}
		}
	case "anthropic-messages":
		if raw["system"] != nil {
			if e := add("system", raw["system"]); e != nil {
				return q, e
			}
		}
		for _, value := range arrayValue(raw["messages"]) {
			m := objectValue(value)
			role := fieldText(m, "role")
			if !containsField([]string{"user", "assistant", "system"}, role) {
				return q, protocolFailure()
			}
			msg := protocolMessage{Role: role}
			var results []protocolMessage
			if text, ok := m["content"].(string); ok {
				msg.Content = []protocolBlock{{Kind: "text", Text: text}}
			} else {
				if _, ok := m["content"].([]any); !ok {
					return q, protocolFailure()
				}
				for _, value := range arrayValue(m["content"]) {
					block := objectValue(value)
					switch fieldText(block, "type") {
					case "tool_use":
						if role != "assistant" {
							return q, protocolFailure()
						}
						arguments, e := json.Marshal(block["input"])
						if e != nil {
							return q, protocolFailure()
						}
						msg.Calls = append(msg.Calls, protocolCall{fieldText(block, "id"), fieldText(block, "name"), string(arguments)})
					case "tool_result":
						if role != "user" {
							return q, protocolFailure()
						}
						parts, e := protocolContent(block["content"], format)
						if e != nil {
							return q, e
						}
						if bad, _ := block["is_error"].(bool); bad {
							parts = append([]protocolBlock{{Kind: "text", Text: "Tool error: "}}, parts...)
						}
						results = append(results, protocolMessage{Role: "tool", CallID: fieldText(block, "tool_use_id"), Content: parts})
					case "thinking":
						msg.Reasoning += fieldText(block, "thinking")
					default:
						parts, e := protocolContent([]any{block}, format)
						if e != nil {
							return q, e
						}
						msg.Content = append(msg.Content, parts...)
					}
				}
			}
			q.Messages = append(q.Messages, results...)
			if len(msg.Content) > 0 || len(msg.Calls) > 0 || msg.Reasoning != "" {
				q.Messages = append(q.Messages, msg)
			}
		}
	case "openai-responses":
		if raw["instructions"] != nil {
			if e := add("system", raw["instructions"]); e != nil {
				return q, e
			}
		}
		if text, ok := raw["input"].(string); ok {
			if e := add("user", text); e != nil {
				return q, e
			}
		} else {
			if _, ok := raw["input"].([]any); !ok {
				return q, protocolFailure()
			}
			reasoning := ""
			for _, value := range arrayValue(raw["input"]) {
				m := objectValue(value)
				kind := fieldText(m, "type")
				switch kind {
				case "reasoning":
					if fieldText(m, "encrypted_content") != "" {
						return q, protocolFailure()
					}
					for _, summary := range arrayValue(m["summary"]) {
						reasoning += fieldText(objectValue(summary), "text")
					}
				case "function_call", "custom_tool_call":
					call := protocolCall{fieldText(m, "call_id"), namespacedToolName(fieldText(m, "namespace"), fieldText(m, "name")), fieldText(m, "arguments")}
					if kind == "custom_tool_call" {
						args, _ := json.Marshal(map[string]any{"input": m["input"]})
						call.Arguments = string(args)
					}
					if len(q.Messages) == 0 || q.Messages[len(q.Messages)-1].Role != "assistant" {
						q.Messages = append(q.Messages, protocolMessage{Role: "assistant", Reasoning: reasoning})
						reasoning = ""
					}
					msg := &q.Messages[len(q.Messages)-1]
					if reasoning != "" {
						msg.Reasoning += reasoning
						reasoning = ""
					}
					msg.Calls = append(msg.Calls, call)
				case "function_call_output", "custom_tool_call_output":
					if e := add("tool", m["output"]); e != nil {
						return q, e
					}
					q.Messages[len(q.Messages)-1].CallID = fieldText(m, "call_id")
				case "message", "":
					if e := add(fieldText(m, "role"), m["content"]); e != nil {
						return q, e
					}
					if q.Messages[len(q.Messages)-1].Role == "assistant" {
						q.Messages[len(q.Messages)-1].Reasoning = reasoning
						reasoning = ""
					}
				default:
					return q, protocolFailure()
				}
			}
		}
	default:
		return q, protocolFailure()
	}
	var addTool func(map[string]any, string) error
	addTool = func(tool map[string]any, namespace string) error {
		kind := fieldText(tool, "type")
		if format == "openai-responses" && kind == "namespace" {
			if namespace != "" || fieldText(tool, "name") == "" {
				return protocolFailure()
			}
			for _, value := range arrayValue(tool["tools"]) {
				child := objectValue(value)
				if description := fieldText(tool, "description"); description != "" {
					copy := map[string]any{}
					for k, v := range child {
						copy[k] = v
					}
					copy["description"] = description + "\n" + fieldText(child, "description")
					child = copy
				}
				if err := addTool(child, fieldText(tool, "name")); err != nil {
					return err
				}
			}
			return nil
		}
		if format == "openai-responses" && containsField([]string{"web_search", "web_search_preview", "tool_search"}, kind) {
			q.DisabledTools = append(q.DisabledTools, kind)
			return nil
		}
		if format == "openai-completions" {
			if kind != "function" {
				return protocolFailure()
			}
			tool = objectValue(tool["function"])
		}
		custom := format == "openai-responses" && kind == "custom"
		if format == "openai-responses" && kind != "function" && !custom {
			return protocolFailure()
		}
		if format == "anthropic-messages" && kind != "" && kind != "custom" {
			return protocolFailure()
		}
		schema := tool["parameters"]
		if format == "anthropic-messages" {
			schema = tool["input_schema"]
		}
		if custom {
			schema = map[string]any{"type": "object", "properties": map[string]any{"input": map[string]any{"type": "string"}}, "required": []string{"input"}, "additionalProperties": false}
		}
		if schema == nil {
			schema = map[string]any{"type": "object", "properties": map[string]any{}}
		}
		name := fieldText(tool, "name")
		if name == "" {
			return protocolFailure()
		}
		wireName := namespacedToolName(namespace, name)
		for _, existing := range q.Tools {
			if existing.Name == wireName {
				return protocolFailure()
			}
		}
		description := fieldText(tool, "description")
		if custom && tool["format"] != nil {
			format, _ := json.Marshal(tool["format"])
			description += "\nInput format: " + string(format)
		}
		q.Tools = append(q.Tools, protocolTool{Name: wireName, OriginalName: name, Namespace: namespace, Description: description, Schema: schema, Custom: custom})
		return nil
	}
	for _, value := range arrayValue(raw["tools"]) {
		if err := addTool(objectValue(value), ""); err != nil {
			return q, err
		}
	}
	if len(q.DisabledTools) > 0 {
		q.Messages = append(q.Messages, protocolMessage{Role: "system", Content: []protocolBlock{{Kind: "text", Text: "This model connection does not provide provider-hosted tools: " + strings.Join(q.DisabledTools, ", ") + ". Use only the supplied client tools; do not invent unavailable tool results."}}})
	}
	switch choice := raw["tool_choice"].(type) {
	case string:
		q.Choice = choice
	case map[string]any:
		kind := fieldText(choice, "type")
		if format == "anthropic-messages" {
			switch kind {
			case "auto":
				q.Choice = "auto"
			case "any":
				q.Choice = "required"
			case "none":
				q.Choice = "none"
			case "tool":
				q.Choice = "named"
				q.NamedTool = namespacedToolName(fieldText(choice, "namespace"), fieldText(choice, "name"))
			default:
				return q, protocolFailure()
			}
			if disable, ok := choice["disable_parallel_tool_use"].(bool); ok {
				p := !disable
				q.Parallel = &p
			}
		} else {
			if kind != "function" && kind != "custom" {
				return q, protocolFailure()
			}
			q.Choice = "named"
			q.NamedTool = namespacedToolName(fieldText(choice, "namespace"), fieldText(choice, "name"))
			if format == "openai-completions" {
				q.NamedTool = fieldText(objectValue(choice["function"]), "name")
			}
		}
	}
	if q.Choice == "required" && len(q.Tools) == 0 {
		return q, protocolFailure()
	}
	if !containsField([]string{"", "auto", "none", "required", "named"}, q.Choice) {
		return q, protocolFailure()
	}
	if q.Choice == "named" {
		found := false
		for _, tool := range q.Tools {
			if tool.Name == q.NamedTool {
				found = true
			}
		}
		if !found {
			return q, protocolFailure()
		}
	}
	for _, msg := range q.Messages {
		if msg.Role == "tool" && msg.CallID == "" {
			return q, protocolFailure()
		}
		for _, call := range msg.Calls {
			var args map[string]any
			if msg.Role != "assistant" || call.Name == "" || call.ID == "" || json.Unmarshal([]byte(call.Arguments), &args) != nil || args == nil {
				return q, protocolFailure()
			}
		}
	}
	if len(q.Messages) == 0 {
		return q, protocolFailure()
	}
	return q, nil
}

func encodeProtocolContent(parts []protocolBlock, format string) ([]any, error) {
	content := []any{}
	for _, p := range parts {
		if p.Kind == "text" {
			kind := "text"
			if format == "openai-responses" {
				kind = "input_text"
			}
			content = append(content, map[string]any{"type": kind, "text": p.Text})
		} else if p.Kind == "image" {
			switch format {
			case "openai-completions":
				content = append(content, map[string]any{"type": "image_url", "image_url": map[string]any{"url": p.URL}})
			case "openai-responses":
				content = append(content, map[string]any{"type": "input_image", "image_url": p.URL})
			case "anthropic-messages":
				source := map[string]any{"type": "url", "url": p.URL}
				if strings.HasPrefix(p.URL, "data:") {
					header, data, ok := strings.Cut(p.URL[5:], ",")
					if !ok || !strings.HasSuffix(header, ";base64") {
						return nil, protocolFailure()
					}
					source = map[string]any{"type": "base64", "media_type": strings.TrimSuffix(header, ";base64"), "data": data}
				}
				content = append(content, map[string]any{"type": "image", "source": source})
			}
		} else {
			return nil, protocolFailure()
		}
	}
	return content, nil
}
func (q protocolRequest) encode(format, model string) ([]byte, error) {
	out := map[string]any{"model": model, "stream": q.Stream}
	for _, key := range []string{"temperature", "top_p"} {
		if q.Params[key] != nil {
			out[key] = q.Params[key]
		}
	}
	max := q.Params["max_output_tokens"]
	if max == nil {
		max = q.Params["max_completion_tokens"]
	}
	if max == nil {
		max = q.Params["max_tokens"]
	}
	if max != nil {
		key := "max_tokens"
		if format == "openai-responses" {
			key = "max_output_tokens"
		}
		out[key] = max
	} else if format == "anthropic-messages" {
		out["max_tokens"] = 8192
	}
	stop := q.Params["stop"]
	if stop == nil {
		stop = q.Params["stop_sequences"]
	}
	if stop != nil && format != "openai-responses" {
		key := "stop"
		if format == "anthropic-messages" {
			key = "stop_sequences"
			if s, ok := stop.(string); ok {
				stop = []string{s}
			}
		}
		out[key] = stop
	}
	if effort := q.Params["reasoning_effort"]; effort != nil {
		switch format {
		case "openai-completions":
			out["reasoning_effort"] = effort
		case "openai-responses":
			out["reasoning"] = map[string]any{"effort": effort}
		case "anthropic-messages":
			out["thinking"] = map[string]any{"type": "adaptive"}
			out["output_config"] = map[string]any{"effort": effort}
		}
	}
	if rawFormat := q.Params["response_format"]; rawFormat != nil {
		spec := objectValue(rawFormat)
		kind := fieldText(spec, "type")
		if kind == "json_schema" {
			schema := objectValue(spec["json_schema"])
			if len(schema) == 0 {
				schema = map[string]any{}
				for k, v := range spec {
					if k != "type" {
						schema[k] = v
					}
				}
			}
			if schema["name"] == nil {
				schema["name"] = "output"
			}
			switch format {
			case "openai-completions":
				out["response_format"] = map[string]any{"type": "json_schema", "json_schema": schema}
			case "openai-responses":
				flat := map[string]any{"type": "json_schema"}
				for k, v := range schema {
					flat[k] = v
				}
				if flat["name"] == nil {
					flat["name"] = "output"
				}
				out["text"] = map[string]any{"format": flat}
			case "anthropic-messages":
				config := objectValue(out["output_config"])
				if config == nil {
					config = map[string]any{}
				}
				config["format"] = map[string]any{"type": "json_schema", "schema": schema["schema"]}
				out["output_config"] = config
			}
		} else if kind == "json_object" {
			if format == "anthropic-messages" {
				return nil, protocolFailure()
			}
			if format == "openai-responses" {
				out["text"] = map[string]any{"format": spec}
			} else {
				out["response_format"] = spec
			}
		} else if kind != "text" {
			return nil, protocolFailure()
		}
	}
	messages := []any{}
	system := []any{}
	pendingImages := []protocolBlock{}
	flushImages := func() error {
		if len(pendingImages) == 0 {
			return nil
		}
		content, err := encodeProtocolContent(pendingImages, format)
		if err != nil {
			return err
		}
		messages = append(messages, map[string]any{"role": "user", "content": content})
		pendingImages = nil
		return nil
	}
	for _, m := range q.Messages {
		if format == "openai-completions" && m.Role != "tool" {
			if err := flushImages(); err != nil {
				return nil, err
			}
		}
		parts := m.Content
		if format == "openai-completions" && m.Role == "tool" {
			text := []protocolBlock{}
			images := []protocolBlock{}
			for _, block := range parts {
				if block.Kind == "image" {
					images = append(images, block)
				} else {
					text = append(text, block)
				}
			}
			if len(images) > 0 {
				pendingImages = append(pendingImages, protocolBlock{Kind: "text", Text: "Images from tool call " + m.CallID + ":"})
				pendingImages = append(pendingImages, images...)
				if len(text) == 0 {
					text = []protocolBlock{{Kind: "text", Text: "Tool returned image content."}}
				}
				parts = text
			}
		}
		if m.Reasoning != "" && format != "openai-completions" {
			parts = append([]protocolBlock{{Kind: "text", Text: "Previous model reasoning:\n" + m.Reasoning}}, parts...)
		}
		content, e := encodeProtocolContent(parts, format)
		if e != nil {
			return nil, e
		}
		switch format {
		case "openai-completions":
			row := map[string]any{"role": m.Role, "content": content}
			if len(content) == 0 {
				row["content"] = nil
			}
			if m.Role == "tool" {
				row["tool_call_id"] = m.CallID
			}
			if m.Reasoning != "" {
				row["reasoning_content"] = m.Reasoning
			}
			if len(m.Calls) > 0 {
				calls := []any{}
				for _, c := range m.Calls {
					calls = append(calls, map[string]any{"type": "function", "id": c.ID, "function": map[string]any{"name": c.Name, "arguments": c.Arguments}})
				}
				row["tool_calls"] = calls
			}
			messages = append(messages, row)
		case "anthropic-messages":
			if m.Role == "system" && len(messages) == 0 {
				system = append(system, content...)
				continue
			}
			if m.Role == "tool" {
				messages = append(messages, map[string]any{"role": "user", "content": []any{map[string]any{"type": "tool_result", "tool_use_id": m.CallID, "content": content}}})
				continue
			}
			for _, c := range m.Calls {
				var input map[string]any
				if json.Unmarshal([]byte(c.Arguments), &input) != nil || input == nil {
					return nil, protocolFailure()
				}
				content = append(content, map[string]any{"type": "tool_use", "id": c.ID, "name": c.Name, "input": input})
			}
			messages = append(messages, map[string]any{"role": m.Role, "content": content})
		case "openai-responses":
			if m.Role == "tool" {
				var output any = content
				if text, e := textBlocks(m.Content); e == nil {
					output = text
				}
				messages = append(messages, map[string]any{"type": "function_call_output", "call_id": m.CallID, "output": output})
				continue
			}
			if len(content) > 0 {
				if m.Role == "assistant" {
					for _, p := range content {
						if b := objectValue(p); fieldText(b, "type") == "input_text" {
							b["type"] = "output_text"
						}
					}
				}
				messages = append(messages, map[string]any{"type": "message", "role": m.Role, "content": content})
			}
			for _, c := range m.Calls {
				messages = append(messages, map[string]any{"type": "function_call", "call_id": c.ID, "name": c.Name, "arguments": c.Arguments})
			}
		}
	}
	if format == "openai-completions" {
		if err := flushImages(); err != nil {
			return nil, err
		}
	}
	switch format {
	case "openai-completions":
		out["messages"] = messages
		if q.Stream {
			out["stream_options"] = map[string]any{"include_usage": true}
		}
	case "anthropic-messages":
		merged := []any{}
		for _, value := range messages {
			row := objectValue(value)
			if len(merged) > 0 && fieldText(objectValue(merged[len(merged)-1]), "role") == fieldText(row, "role") {
				last := objectValue(merged[len(merged)-1])
				last["content"] = append(arrayValue(last["content"]), arrayValue(row["content"])...)
			} else {
				merged = append(merged, row)
			}
		}
		out["messages"] = merged
		if len(system) > 0 {
			out["system"] = system
		}
	case "openai-responses":
		out["input"] = messages
		out["store"] = false
	}
	if len(q.Tools) > 0 {
		tools := []any{}
		for _, t := range q.Tools {
			switch format {
			case "openai-completions":
				tools = append(tools, map[string]any{"type": "function", "function": map[string]any{"name": t.Name, "description": t.Description, "parameters": t.Schema}})
			case "anthropic-messages":
				tools = append(tools, map[string]any{"name": t.Name, "description": t.Description, "input_schema": t.Schema})
			case "openai-responses":
				tools = append(tools, map[string]any{"type": "function", "name": t.Name, "description": t.Description, "parameters": t.Schema, "strict": false})
			}
		}
		out["tools"] = tools
		if q.Choice != "" {
			var choice any = q.Choice
			if format == "anthropic-messages" {
				kind := q.Choice
				if kind == "required" {
					kind = "any"
				}
				choice = map[string]any{"type": kind}
				if kind == "named" {
					choice = map[string]any{"type": "tool", "name": q.NamedTool}
				}
				if q.Parallel != nil {
					objectValue(choice)["disable_parallel_tool_use"] = !*q.Parallel
				}
			} else if q.Choice == "named" {
				choice = map[string]any{"type": "function", "name": q.NamedTool}
				if format == "openai-completions" {
					choice = map[string]any{"type": "function", "function": map[string]any{"name": q.NamedTool}}
				}
			}
			out["tool_choice"] = choice
		}
		if q.Parallel != nil && format != "anthropic-messages" {
			out["parallel_tool_calls"] = *q.Parallel
		}
	}
	return json.Marshal(out)
}
func prepareProtocolBridge(body []byte, from, to, model string) ([]byte, *protocolBridge, error) {
	if from == to {
		var raw map[string]json.RawMessage
		if json.Unmarshal(body, &raw) != nil {
			return nil, nil, protocolFailure()
		}
		raw["model"], _ = json.Marshal(model)
		out, e := json.Marshal(raw)
		return out, nil, e
	}
	q, e := decodeProtocolRequest(body, from)
	if e != nil {
		return nil, nil, e
	}
	out, e := q.encode(to, model)
	return out, &protocolBridge{from: from, to: to, request: q}, e
}

func namespacedToolName(namespace, name string) string {
	if namespace == "" {
		return name
	}
	wire := namespace + "__" + name
	if len(wire) <= 64 {
		return wire
	}
	hash := sha256.Sum256([]byte(namespace + "." + name))
	return fmt.Sprintf("roami_%x", hash[:24])
}
