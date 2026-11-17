package modelgateway

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"time"
)

type qualityProbe struct {
	Rule   string
	Record *MonitorRecord
}
type probeSink struct {
	header http.Header
	status int
}

func (s *probeSink) Header() http.Header { return s.header }
func (s *probeSink) WriteHeader(status int) {
	if s.status == 0 {
		s.status = status
	}
}
func (s *probeSink) Write(data []byte) (int, error) {
	if s.status == 0 {
		s.status = 200
	}
	return len(data), nil
}
func (s *probeSink) Flush() {}
func (h *Handler) runQualityProbe(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		reject(w, 405, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return
	}
	if h.Monitor == nil || h.Catalog == nil {
		reject(w, 503, "MODEL_MONITOR_UNAVAILABLE")
		return
	}
	var input struct {
		SourceID string `json:"sourceId"`
		Model    string `json:"model"`
		Rule     string `json:"rule"`
	}
	if decodeBody(w, r, &input) != nil || !catalogID.MatchString(input.SourceID) || len(input.Model) > 200 || !containsField([]string{"answer", "json", "tool"}, input.Rule) {
		reject(w, 400, "INVALID_MONITOR_QUERY")
		return
	}
	h.Catalog.mu.Lock()
	catalog := h.Catalog.snapshot()
	h.Catalog.mu.Unlock()
	var alias CatalogModel
	found := false
	for _, model := range catalog.Models {
		for _, candidate := range model.Candidates {
			if candidate.SourceID == input.SourceID && candidate.Model == input.Model {
				alias = CatalogModel{ID: model.ID, Name: model.Name, Strategy: "fixed", Protocol: model.Protocol, Candidates: []ModelCandidate{candidate}}
				found = true
				break
			}
		}
		if found {
			break
		}
	}
	if !found {
		reject(w, 404, "MODEL_NOT_CONFIGURED")
		return
	}
	catalog.Models = []CatalogModel{alias}
	prompt := "What is 1 + 1? Reply with only the digit 2."
	if input.Rule == "json" {
		prompt = "What is 1 + 1? Reply with exactly one JSON object: {\"answer\":2}. No other text."
	}
	if input.Rule == "tool" {
		prompt = "Compute 1 + 1 and call report_answer with the numeric answer. Do not reply with text."
	}
	payload := map[string]any{"model": alias.ID, "stream": true, "max_tokens": 256, "messages": []any{map[string]any{"role": "user", "content": prompt}}}
	if input.Rule == "tool" {
		payload["tools"] = []any{map[string]any{"type": "function", "function": map[string]any{"name": "report_answer", "description": "Report the arithmetic result", "parameters": map[string]any{"type": "object", "properties": map[string]any{"answer": map[string]string{"type": "number"}}, "required": []string{"answer"}, "additionalProperties": false}}}}
		payload["tool_choice"] = map[string]any{"type": "function", "function": map[string]string{"name": "report_answer"}}
	}
	raw, _ := json.Marshal(payload)
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	probe := &qualityProbe{Rule: input.Rule}
	ctx = context.WithValue(ctx, qualityProbeContext{}, probe)
	request, _ := http.NewRequestWithContext(ctx, "POST", "http://gateway/v1/chat/completions", bytes.NewReader(raw))
	request.Header.Set("Content-Type", "application/json")
	sink := &probeSink{header: http.Header{}}
	h.forwardCatalog(sink, request, catalog, "roami_monitor", "openai-completions")
	if probe.Record == nil {
		code := sink.header.Get("X-Roami-Model-Error")
		if !strings.HasPrefix(code, "MODEL_") {
			code = "MODEL_MONITOR_CHECK_FAILED"
		}
		status := sink.status
		if status < 400 {
			status = 503
		}
		reject(w, status, code)
		return
	}
	writeJSON(w, 200, map[string]any{"data": probe.Record})
}
