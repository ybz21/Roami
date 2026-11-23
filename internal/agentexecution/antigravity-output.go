package agentexecution

import (
	"encoding/json"

	"github.com/ybz21/Roami/internal/agent"
)

func (p *structuredOutput) consumeAntigravity(line []byte) {
	var e struct {
		Event          string `json:"event"`
		ConversationID string `json:"conversation_id"`
		StepUpdate     struct {
			ConversationID string `json:"conversation_id"`
		} `json:"step_update"`
		Result struct {
			ConversationID string `json:"conversation_id"`
			Status         string `json:"status"`
			Response       string `json:"response"`
			FinishedReason string `json:"finished_reason"`
		} `json:"result"`
	}
	if p.complete || p.failed || json.Unmarshal(line, &e) != nil {
		p.invalid = true
		return
	}
	if !p.initialized {
		if e.Event != "init" || !agent.ValidAntigravityConversationID(e.ConversationID) {
			p.invalid = true
			return
		}
		p.bind(e.ConversationID)
		p.initialized = true
		return
	}
	switch e.Event {
	case "step_update":
		p.bind(e.StepUpdate.ConversationID)
	case "result":
		p.bind(e.Result.ConversationID)
		p.failed = e.Result.Status != "SUCCESS" || e.Result.FinishedReason != ""
		p.complete = !p.failed
		if p.complete {
			p.text.Write([]byte(e.Result.Response))
		}
	default:
		p.invalid = true
	}
}
