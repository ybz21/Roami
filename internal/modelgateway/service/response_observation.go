package service

import (
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/modelgateway/accounting"
	"github.com/ybz21/Roami/internal/modelgateway/monitor"
	"github.com/ybz21/Roami/internal/modelgateway/protocol"
	"github.com/ybz21/Roami/internal/modelgateway/routing"
)

func checkArithmeticObject(raw string) bool {
	var fields map[string]json.RawMessage
	if json.Unmarshal([]byte(raw), &fields) != nil || len(fields) != 1 {
		return false
	}
	var answer *float64
	return json.Unmarshal(fields["answer"], &answer) == nil && answer != nil && *answer == 2
}

type qualityProbeContext struct{}

func (h *Handler) observeAttempt(r *http.Request, leaf routing.Leaf, call accounting.Call, status int, code string, usage *accounting.Usage, o *protocol.ResponseObservation, requestID string, attempt int) monitor.Record {
	finished := time.Now()
	successful, first, speed := o.Metrics(status, usage, finished)
	quality, rule := "unchecked", ""
	if expected, ok := r.Context().Value(qualityProbeContext{}).(*qualityProbe); ok {
		rule = expected.Rule
		quality = "fail"
		if text, tool, arguments, complete := o.ProbePayload(); successful && complete {
			passed := false
			switch expected.Rule {
			case "answer":
				passed = strings.TrimSpace(text) == "2"
			case "json":
				passed = checkArithmeticObject(text)
			case "tool":
				passed = tool == "report_answer" && checkArithmeticObject(arguments)
			}
			if passed {
				quality = "pass"
			}
		}
	}
	h.routing.Observe(leaf, usage, successful, first, speed, h.state.now)
	if requestID == "" {
		attempt = 0
	}
	record := monitor.Record{At: h.state.now().UnixMilli(), SourceID: call.SourceID, Model: call.Model, RouteID: call.RouteID, Account: routing.AccountLabel(leaf.Account), Success: successful, Status: status, Error: monitor.ErrorCode(code), Duration: o.Elapsed(finished).Milliseconds(), FirstToken: first, TokensPerSecond: speed, Quality: quality, QualityRule: rule, RequestID: requestID, Attempt: attempt, CallID: call.ID}
	if requestID != "" {
		for i := len(leaf.Ancestors) - 1; i >= 0; i-- {
			record.GroupPath = append(record.GroupPath, strings.TrimPrefix(leaf.Ancestors[i], "group/"))
		}
	}
	if probe, ok := r.Context().Value(qualityProbeContext{}).(*qualityProbe); ok {
		copy := record
		probe.Record = &copy
	}
	if h.Monitor != nil {
		_ = h.Monitor.Append(record)
	}
	return record
}
