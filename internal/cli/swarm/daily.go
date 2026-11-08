package swarm

import (
	"context"
	"fmt"
	"io"
	"os"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func wakeDaily(ctx context.Context, rt runtime.Runtime, path string, o commandOptions, w io.Writer, jsonOutput bool) error {
	if os.Getenv("ROAMI_AGENT_CALLER_ROLE") != "" || os.Getenv("ROAMI_AGENT_TURN_ID") != "" {
		return fmt.Errorf("EXTERNAL_TRIGGER_REQUIRED: daily wakeups reuse an existing user goal")
	}
	body := map[string]any{"dryRun": o.switches["dry-run"]}
	for flag, field := range map[string]string{"delegation": "delegationId", "project": "projectId", "main-conversation": "conversationId", "timezone": "timezone", "date": "date", "slot": "slot"} {
		value, err := o.required(flag)
		if err != nil {
			return err
		}
		body[field] = value
	}
	client, err := newRuntimeClient(rt)
	if err != nil {
		return err
	}
	defer client.close()
	raw, err := client.request(ctx, "POST", path+"/goal/daily", body)
	if err != nil {
		return err
	}
	if jsonOutput {
		return writeJSON(w, raw)
	}
	var result struct {
		State string `json:"state"`
		JobID string `json:"jobId"`
	}
	if err := responseData(raw, &result); err != nil {
		return err
	}
	_, err = fmt.Fprintln(w, result.State, result.JobID)
	return err
}
