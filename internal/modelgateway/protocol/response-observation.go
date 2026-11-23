package protocol

import (
	"bytes"
	"encoding/json"
	"io"
	"strings"
	"time"
)

type ResponseObservation struct {
	protocol                          string
	started                           time.Time
	stream                            bool
	first                             time.Time
	buffer                            []byte
	text                              strings.Builder
	toolName                          string
	toolArguments                     strings.Builder
	eof, terminal, truncated, invalid bool
}

func NewResponseObservation(protocol string, started time.Time) *ResponseObservation {
	return &ResponseObservation{protocol: protocol, started: started}
}
func (o *ResponseObservation) appendText(value string) {
	if value == "" {
		return
	}
	if o.first.IsZero() {
		o.first = time.Now()
	}
	if o.text.Len()+len(value) <= 4096 {
		o.text.WriteString(value)
	} else {
		o.truncated = true
	}
}
func (o *ResponseObservation) appendArguments(value string) {
	if value == "" {
		return
	}
	if o.first.IsZero() {
		o.first = time.Now()
	}
	if o.toolArguments.Len()+len(value) <= 4096 {
		o.toolArguments.WriteString(value)
	} else {
		o.truncated = true
	}
}
func (o *ResponseObservation) message(raw []byte) {
	if bytes.Equal(raw, []byte("[DONE]")) {
		o.terminal = true
		return
	}
	var value map[string]json.RawMessage
	if json.Unmarshal(raw, &value) != nil {
		o.invalid = true
		return
	}
	text := func(raw json.RawMessage) string { var result string; _ = json.Unmarshal(raw, &result); return result }
	kind := text(value["type"])
	switch kind {
	case "message_stop", "response.completed":
		o.terminal = true
	case "response.output_text.delta":
		o.appendText(text(value["delta"]))
	case "response.function_call_arguments.delta":
		o.appendArguments(text(value["delta"]))
	case "response.output_item.added":
		var item struct {
			Name string `json:"name"`
			Type string `json:"type"`
		}
		_ = json.Unmarshal(value["item"], &item)
		if item.Type == "function_call" {
			o.toolName = item.Name
		}
	case "content_block_start":
		var block struct {
			Type string `json:"type"`
			Name string `json:"name"`
		}
		_ = json.Unmarshal(value["content_block"], &block)
		if block.Type == "tool_use" {
			o.toolName = block.Name
		}
	case "content_block_delta":
		var delta struct {
			Text    string `json:"text"`
			Partial string `json:"partial_json"`
		}
		_ = json.Unmarshal(value["delta"], &delta)
		o.appendText(delta.Text)
		o.appendArguments(delta.Partial)
	}
	var choices []struct {
		Delta   json.RawMessage `json:"delta"`
		Message json.RawMessage `json:"message"`
	}
	if json.Unmarshal(value["choices"], &choices) == nil {
		for _, choice := range choices {
			for _, raw := range []json.RawMessage{choice.Delta, choice.Message} {
				var message struct {
					Content string `json:"content"`
					Tools   []struct {
						Function struct {
							Name      string `json:"name"`
							Arguments string `json:"arguments"`
						} `json:"function"`
					} `json:"tool_calls"`
				}
				if json.Unmarshal(raw, &message) == nil {
					o.appendText(message.Content)
					for _, tool := range message.Tools {
						if tool.Function.Name != "" {
							o.toolName = tool.Function.Name
						}
						o.appendArguments(tool.Function.Arguments)
					}
				}
			}
		}
	}
	var content []struct {
		Type  string          `json:"type"`
		Text  string          `json:"text"`
		Name  string          `json:"name"`
		Input json.RawMessage `json:"input"`
	}
	if json.Unmarshal(value["content"], &content) == nil {
		for _, block := range content {
			if block.Type == "text" {
				o.appendText(block.Text)
			}
			if block.Type == "tool_use" {
				o.toolName = block.Name
				o.appendArguments(string(block.Input))
			}
		}
	}
	var output []struct {
		Type      string `json:"type"`
		Name      string `json:"name"`
		Arguments string `json:"arguments"`
		Content   []struct {
			Text string `json:"text"`
		} `json:"content"`
	}
	if json.Unmarshal(value["output"], &output) == nil {
		for _, item := range output {
			for _, block := range item.Content {
				o.appendText(block.Text)
			}
			if item.Type == "function_call" {
				o.toolName = item.Name
				o.appendArguments(item.Arguments)
			}
		}
	}
}
func (o *ResponseObservation) feed(data []byte) {
	if !o.stream {
		if len(o.buffer)+len(data) <= 64<<10 {
			o.buffer = append(o.buffer, data...)
		} else {
			o.truncated = true
		}
		return
	}
	for len(data) > 0 {
		n := bytes.IndexByte(data, '\n')
		if n < 0 {
			if len(o.buffer)+len(data) <= 64<<10 {
				o.buffer = append(o.buffer, data...)
			} else {
				o.truncated = true
				o.buffer = nil
			}
			return
		}
		line := data[:n]
		data = data[n+1:]
		if len(o.buffer)+len(line) <= 64<<10 {
			o.buffer = append(o.buffer, line...)
			trimmed := bytes.TrimSpace(o.buffer)
			if bytes.HasPrefix(trimmed, []byte("data:")) {
				o.message(bytes.TrimSpace(trimmed[5:]))
			}
		} else {
			o.truncated = true
		}
		o.buffer = nil
	}
}

type observedResponseBody struct {
	io.ReadCloser
	observation *ResponseObservation
}

func (b *observedResponseBody) Read(data []byte) (int, error) {
	n, err := b.ReadCloser.Read(data)
	if n > 0 {
		b.observation.feed(data[:n])
	}
	if err == io.EOF {
		b.observation.eof = true
		if !b.observation.stream && !b.observation.truncated {
			b.observation.message(b.observation.buffer)
		}
	}
	return n, err
}
func (o *ResponseObservation) Wrap(body io.ReadCloser, stream bool) io.ReadCloser {
	o.stream = stream
	return &observedResponseBody{ReadCloser: body, observation: o}
}

func (o *ResponseObservation) Metrics(status int, usage *Usage, finished time.Time) (bool, *float64, *float64) {
	successful := status >= 200 && status < 300 && (o.stream && o.terminal || !o.stream && o.eof) && !o.invalid
	var first, speed *float64
	if o.stream && !o.first.IsZero() {
		latency := float64(o.first.Sub(o.started)) / float64(time.Millisecond)
		first = &latency
		if usage != nil && usage.Output > 0 && finished.After(o.first) {
			rate := float64(usage.Output) / finished.Sub(o.first).Seconds()
			speed = &rate
		}
	}
	return successful, first, speed
}

func (o *ResponseObservation) ProbePayload() (text, toolName, arguments string, complete bool) {
	return o.text.String(), o.toolName, o.toolArguments.String(), !o.truncated
}

func (o *ResponseObservation) Elapsed(finished time.Time) time.Duration {
	return finished.Sub(o.started)
}
