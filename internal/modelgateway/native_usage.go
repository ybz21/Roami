package modelgateway

import (
	"bytes"
	"encoding/json"
)

type nativeUsageCapture struct {
	protocol             string
	stream               bool
	buffer               []byte
	chat                 usageCapture
	usage                *Usage
	done, invalid, delta bool
}

func nativeUsage(raw json.RawMessage, protocol string) *Usage {
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil {
		return nil
	}
	read := func(key string) (int64, bool) {
		var n *int64
		v, ok := fields[key]
		if !ok || json.Unmarshal(v, &n) != nil || n == nil || *n < 0 || *n > 100_000_000 {
			return 0, false
		}
		return *n, true
	}
	input, ok := read("input_tokens")
	output, okOut := read("output_tokens")
	if !ok || !okOut {
		return nil
	}
	cached := int64(0)
	if protocol == "anthropic-messages" {
		if _, exists := fields["cache_read_input_tokens"]; exists {
			n, valid := read("cache_read_input_tokens")
			if !valid {
				return nil
			}
			cached = n
		}
		if _, exists := fields["cache_creation_input_tokens"]; exists {
			n, valid := read("cache_creation_input_tokens")
			if !valid {
				return nil
			}
			input += n
		}
		input += cached
	} else {
		var details struct {
			Cached int64 `json:"cached_tokens"`
		}
		if raw := fields["input_tokens_details"]; len(raw) > 0 && string(raw) != "null" && json.Unmarshal(raw, &details) != nil {
			return nil
		}
		cached = details.Cached
	}
	if input > 100_000_000 || cached < 0 || cached > input {
		return nil
	}
	return &Usage{input, output, cached}
}
func (c *nativeUsageCapture) feed(data []byte) {
	if c.protocol == "openai-completions" {
		c.chat.stream = c.stream
		c.chat.feed(data)
		return
	}
	for len(data) > 0 {
		n := len(data)
		line := bytes.IndexByte(data, '\n')
		if c.stream && line >= 0 {
			n = line + 1
		}
		if len(c.buffer)+n > 4<<20 {
			c.invalid = true
			c.buffer = nil
		} else {
			c.buffer = append(c.buffer, data[:n]...)
		}
		data = data[n:]
		if c.stream && line >= 0 {
			if !c.invalid {
				c.event(bytes.TrimSpace(c.buffer))
			}
			c.buffer = nil
		}
	}
}
func (c *nativeUsageCapture) event(line []byte) {
	if !bytes.HasPrefix(line, []byte("data:")) {
		return
	}
	var e map[string]json.RawMessage
	if json.Unmarshal(bytes.TrimSpace(line[5:]), &e) != nil {
		c.invalid = true
		return
	}
	var kind string
	_ = json.Unmarshal(e["type"], &kind)
	switch kind {
	case "response.completed":
		var response struct {
			Usage json.RawMessage `json:"usage"`
		}
		if json.Unmarshal(e["response"], &response) != nil {
			c.invalid = true
			return
		}
		c.usage = nativeUsage(response.Usage, c.protocol)
		c.done = c.usage != nil
	case "message_start":
		var message struct {
			Usage json.RawMessage `json:"usage"`
		}
		if json.Unmarshal(e["message"], &message) != nil {
			c.invalid = true
			return
		}
		c.usage = nativeUsage(message.Usage, c.protocol)
	case "message_delta":
		var usage struct {
			Output *int64 `json:"output_tokens"`
		}
		if json.Unmarshal(e["usage"], &usage) != nil || usage.Output == nil || *usage.Output < 0 || *usage.Output > 100_000_000 {
			c.invalid = true
			return
		}
		if c.usage != nil {
			c.usage.Output = *usage.Output
			c.delta = true
		}
	case "message_stop":
		c.done = c.delta && c.usage != nil
	case "error", "response.failed", "response.incomplete":
		c.invalid = true
	}
}
func (c *nativeUsageCapture) finish(complete bool) *Usage {
	if c.protocol == "openai-completions" {
		return c.chat.finish(complete)
	}
	if c.invalid {
		return nil
	}
	if c.stream {
		if len(c.buffer) > 0 {
			c.event(bytes.TrimSpace(c.buffer))
		}
		if c.done && !c.invalid {
			return c.usage
		}
		return nil
	}
	if !complete {
		return nil
	}
	var response struct {
		Usage  json.RawMessage `json:"usage"`
		Error  json.RawMessage `json:"error"`
		Status string          `json:"status"`
	}
	if json.Unmarshal(c.buffer, &response) != nil || len(response.Error) > 0 && string(response.Error) != "null" || c.protocol == "openai-responses" && response.Status != "completed" {
		return nil
	}
	return nativeUsage(response.Usage, c.protocol)
}
