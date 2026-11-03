package swarm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/agentruntime"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

const responseLimit = 8 << 20

type runtimeClient struct {
	http      *http.Client
	transport *http.Transport
}
type runtimeError struct {
	status int
	code   string
}

func (e *runtimeError) Error() string {
	hint := ""
	switch e.code {
	case "SWARM_PLAN_CHANGED":
		hint = "; run status and use the current --revision"
	case "REQUEST_KEY_CONFLICT":
		hint = "; reuse the original payload, or use a new --key for a new command"
	case "TASK_REVISION_CHANGED", "TASK_RESULT_SUPERSEDED":
		hint = "; inspect the original task before continuing"
	case "SWARM_STOP_REQUIRED":
		hint = "; confirm the current execution has stopped before changing dependencies"
	}
	return fmt.Sprintf("%s (HTTP %d)%s", e.code, e.status, hint)
}
func newRuntimeClient(rt runtime.Runtime) (*runtimeClient, error) {
	paths, err := agentruntime.Resolve(rt.HomeDir, rt.DataDir)
	if err != nil {
		return nil, err
	}
	transport := agentruntime.Transport(paths.Socket)
	return &runtimeClient{http: &http.Client{Transport: transport}, transport: transport}, nil
}
func (c *runtimeClient) close() { c.transport.CloseIdleConnections() }
func (c *runtimeClient) open(ctx context.Context, method, path string, body any) (*http.Response, error) {
	var raw []byte
	var err error
	if body != nil {
		raw, err = json.Marshal(body)
		if err != nil {
			return nil, err
		}
	}
	request, err := http.NewRequestWithContext(ctx, method, "http://roami-agent"+path, bytes.NewReader(raw))
	if err != nil {
		return nil, err
	}
	request.Header.Set("X-Roami-Owner", "local")
	request.Header.Set("Content-Type", "application/json")
	if strings.Contains(path, "/events?") {
		request.Header.Set("Accept", "text/event-stream")
	}
	response, err := c.http.Do(request)
	if err != nil {
		return nil, fmt.Errorf("AGENT_RUNTIME_UNAVAILABLE: %w", err)
	}
	if response.StatusCode >= 400 {
		defer response.Body.Close()
		data, _ := io.ReadAll(io.LimitReader(response.Body, 65536))
		var message struct {
			Error struct {
				Code string `json:"code"`
			} `json:"error"`
		}
		_ = json.Unmarshal(data, &message)
		if message.Error.Code == "" {
			message.Error.Code = "SWARM_REQUEST_REJECTED"
		}
		return nil, &runtimeError{status: response.StatusCode, code: message.Error.Code}
	}
	return response, nil
}
func (c *runtimeClient) request(ctx context.Context, method, path string, body any) (json.RawMessage, error) {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	response, err := c.open(ctx, method, path, body)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(response.Body, responseLimit+1))
	if err != nil {
		return nil, err
	}
	if len(raw) > responseLimit {
		return nil, fmt.Errorf("SWARM_RESPONSE_TOO_LARGE")
	}
	if !json.Valid(raw) {
		return nil, fmt.Errorf("INVALID_SWARM_RESPONSE")
	}
	return json.RawMessage(raw), nil
}
func responseData(raw json.RawMessage, target any) error {
	var envelope struct {
		Data json.RawMessage `json:"data"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return err
	}
	if len(envelope.Data) == 0 || string(envelope.Data) == "null" {
		return fmt.Errorf("INVALID_SWARM_RESPONSE")
	}
	return json.Unmarshal(envelope.Data, target)
}
func writeJSON(w io.Writer, value any) error { return json.NewEncoder(w).Encode(value) }
