package protocol

import (
	"encoding/json"
	"net/http"
)

type upstreamRequestError struct {
	Code     json.RawMessage `json:"code"`
	Param    string          `json:"param"`
	Metadata struct {
		Raw json.RawMessage `json:"raw"`
	} `json:"metadata"`
}

func (o *ResponseObservation) RequestRejection(status int) string {
	if o.stream || !o.eof || o.truncated ||
		(status != http.StatusBadRequest && status != http.StatusRequestEntityTooLarge && status != http.StatusUnprocessableEntity) {
		return ""
	}
	failure := readRequestError(o.buffer)
	if reason := failure.reason(); reason != "" {
		return reason
	}
	raw := failure.Metadata.Raw
	var encoded string
	if json.Unmarshal(raw, &encoded) == nil {
		raw = []byte(encoded)
	}
	return readRequestError(raw).reason()
}

func readRequestError(raw []byte) upstreamRequestError {
	var response struct {
		Error upstreamRequestError `json:"error"`
	}
	if json.Unmarshal(raw, &response) != nil {
		return upstreamRequestError{}
	}
	return response.Error
}

func (e upstreamRequestError) reason() string {
	var code string
	_ = json.Unmarshal(e.Code, &code)
	switch code {
	case "context_length_exceeded", "context_window_exceeded":
		return "context_limit"
	case "max_tokens_exceeded", "max_completion_tokens_exceeded":
		return "output_limit"
	case "invalid_tool_call", "invalid_tool_result", "invalid_tool_schema":
		return "tool_input"
	case "unsupported_parameter", "unsupported_value":
		return "unsupported_parameter"
	}
	switch e.Param {
	case "max_tokens", "max_completion_tokens", "max_output_tokens":
		return "output_tokens"
	case "tools", "tool_choice":
		return "tool_input"
	case "messages", "input":
		return "message_input"
	default:
		return ""
	}
}
