package modelgateway

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type responseObservation struct {
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

func newResponseObservation(protocol string, started time.Time) *responseObservation {
	return &responseObservation{protocol: protocol, started: started}
}
func (o *responseObservation) appendText(value string) {
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
func (o *responseObservation) appendArguments(value string) {
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
func (o *responseObservation) message(raw []byte) {
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
func (o *responseObservation) feed(data []byte) {
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
	observation *responseObservation
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
func retryDelay(value string, now time.Time) time.Duration {
	if seconds, err := strconv.ParseInt(strings.TrimSpace(value), 10, 64); err == nil && seconds > 0 {
		if seconds > int64((1<<63-1)/int64(time.Second)) {
			return time.Duration(1<<63 - 1)
		}
		return time.Duration(seconds) * time.Second
	}
	if at, err := http.ParseTime(value); err == nil && at.After(now) {
		return at.Sub(now)
	}
	return 0
}

func checkArithmeticObject(raw string) bool {
	var fields map[string]json.RawMessage
	if json.Unmarshal([]byte(raw), &fields) != nil || len(fields) != 1 {
		return false
	}
	var answer *float64
	return json.Unmarshal(fields["answer"], &answer) == nil && answer != nil && *answer == 2
}

type qualityProbeContext struct{}

func (h *Handler) observeAttempt(r *http.Request, leaf routingLeaf, call Call, status int, code string, usage *Usage, o *responseObservation) {
	finished := time.Now()
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
	quality, rule := "unchecked", ""
	if expected, ok := r.Context().Value(qualityProbeContext{}).(*qualityProbe); ok {
		rule = expected.Rule
		quality = "fail"
		if successful && !o.truncated {
			passed := false
			switch expected.Rule {
			case "answer":
				passed = strings.TrimSpace(o.text.String()) == "2"
			case "json":
				passed = checkArithmeticObject(o.text.String())
			case "tool":
				passed = o.toolName == "report_answer" && checkArithmeticObject(o.toolArguments.String())
			}
			if passed {
				quality = "pass"
			}
		}
	}
	h.routing.mu.Lock()
	for _, channelID := range append([]string{leaf.ChannelID}, leaf.Ancestors...) {
		channel := h.routing.channel(channelID, h.Ledger.now())
		if usage != nil {
			if time.Since(channel.RecentAt) > time.Hour {
				channel.Input, channel.Output = 0, 0
			}
			channel.Input += usage.Input
			channel.Output += usage.Output
			channel.RecentAt = time.Now()
		}
		if successful && first != nil && speed != nil {
			if channel.Measured.IsZero() {
				channel.FirstToken, channel.Speed = *first, *speed
			} else {
				channel.FirstToken = .3*channel.FirstToken + .7**first
				channel.Speed = .3*channel.Speed + .7**speed
			}
			channel.Measured = h.Ledger.now()
		}
	}
	h.routing.mu.Unlock()
	record := MonitorRecord{At: h.Ledger.now().UnixMilli(), SourceID: call.SourceID, Model: call.Model, RouteID: call.RouteID, Account: routingAccountKey(leaf.Account), Success: successful, Status: status, Error: monitorError(code), Duration: finished.Sub(o.started).Milliseconds(), FirstToken: first, TokensPerSecond: speed, Quality: quality, QualityRule: rule}
	if probe, ok := r.Context().Value(qualityProbeContext{}).(*qualityProbe); ok {
		copy := record
		probe.Record = &copy
	}
	if h.Monitor != nil {
		_ = h.Monitor.Append(record)
	}
}
