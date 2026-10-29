package modelgateway

import (
	"bytes"
	"encoding/json"
)

// OpenAI prompt_tokens includes cached tokens, unlike the gateway pricing input.
type Usage struct{ Input, Output, Cached int64 }

func parseUsage(data []byte) *Usage {
	var value struct {
		Usage *struct {
			Input   *int64 `json:"prompt_tokens"`
			Output  *int64 `json:"completion_tokens"`
			Details struct {
				Cached int64 `json:"cached_tokens"`
			} `json:"prompt_tokens_details"`
		} `json:"usage"`
	}
	if json.Unmarshal(data, &value) != nil || value.Usage == nil || value.Usage.Input == nil || value.Usage.Output == nil {
		return nil
	}
	u := Usage{*value.Usage.Input, *value.Usage.Output, value.Usage.Details.Cached}
	if u.Input < 0 || u.Output < 0 || u.Cached < 0 || u.Cached > u.Input || u.Input > 100_000_000 || u.Output > 100_000_000 {
		return nil
	}
	return &u
}

type usageCapture struct {
	stream   bool
	buffer   []byte
	usage    *Usage
	done     bool
	invalid  bool
	tooLarge bool
}

func (c *usageCapture) feed(data []byte) {
	if !c.stream {
		if len(c.buffer)+len(data) <= 4<<20 {
			c.buffer = append(c.buffer, data...)
		} else {
			c.tooLarge = true
		}
		return
	}
	for len(data) > 0 {
		index := bytes.IndexByte(data, '\n')
		length := len(data)
		if index >= 0 {
			length = index + 1
		}
		if len(c.buffer)+length > 1<<20 {
			c.tooLarge = true
		}
		if !c.tooLarge {
			c.buffer = append(c.buffer, data[:length]...)
		}
		data = data[length:]
		if index >= 0 {
			if !c.tooLarge {
				c.line(bytes.TrimSpace(c.buffer))
			} else {
				c.invalid = true
			}
			c.buffer, c.tooLarge = c.buffer[:0], false
		}
	}
}

func (c *usageCapture) line(line []byte) {
	if !bytes.HasPrefix(line, []byte("data:")) {
		return
	}
	data := bytes.TrimSpace(line[5:])
	if bytes.Equal(data, []byte("[DONE]")) {
		c.done = true
		return
	}
	if c.done {
		return
	}
	var event map[string]json.RawMessage
	if json.Unmarshal(data, &event) != nil || event == nil {
		c.invalid = true
		return
	}
	if raw, ok := event["error"]; ok && !bytes.Equal(raw, []byte("null")) {
		c.invalid = true
	}
	if raw, ok := event["usage"]; ok && !bytes.Equal(raw, []byte("null")) {
		if u := parseUsage(data); u != nil {
			c.usage = u
		} else {
			c.invalid = true
		}
	}
}

func (c *usageCapture) finish(complete bool) *Usage {
	if c.stream {
		if len(c.buffer) > 0 && !c.tooLarge {
			c.line(bytes.TrimSpace(c.buffer))
		}
		// DONE completes the usage receipt even if the caller closes before HTTP EOF.
		if c.invalid || !c.done {
			return nil
		}
		return c.usage
	}
	if !complete || c.tooLarge {
		return nil
	}
	return parseUsage(c.buffer)
}
