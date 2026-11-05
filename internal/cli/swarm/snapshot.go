package swarm

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"regexp"
)

var managedID = regexp.MustCompile(`^sw-[a-f0-9]{32}$`)

type dependency struct {
	Member     string `json:"member,omitempty"`
	Revision   int    `json:"revision"`
	ArtifactID string `json:"artifactId,omitempty"`
	UpstreamID string `json:"upstreamId,omitempty"`
}
type attempt struct {
	RunID      string `json:"runId"`
	State      string `json:"state"`
	SessionID  string `json:"sessionId"`
	FinishedMS int64  `json:"finishedMs"`
	Summary    string `json:"summary"`
}
type workItem struct {
	MemberID      string       `json:"memberId,omitempty"`
	ID            string       `json:"id"`
	Member        string       `json:"member_name"`
	Executor      string       `json:"executor"`
	Title         string       `json:"title"`
	Goal          string       `json:"goal"`
	Acceptance    string       `json:"acceptance"`
	Integration   int          `json:"integration"`
	TaskID        string       `json:"task_id"`
	Revision      int          `json:"revision"`
	State         string       `json:"state"`
	DispatchError string       `json:"dispatch_error"`
	Dependencies  []dependency `json:"dependencies"`
	Attempt       *attempt     `json:"attempt"`
}
type post struct {
	ID            int64  `json:"id"`
	Author        string `json:"author"`
	Text          string `json:"text"`
	TaskID        string `json:"taskId"`
	CreatedMS     int64  `json:"createdMs"`
	DeliveryState string `json:"deliveryState"`
}
type mainMessage struct {
	ID        string `json:"id"`
	Text      string `json:"text"`
	CreatedMS int64  `json:"createdMs"`
}
type member struct {
	ID           string `json:"id"`
	Name         string `json:"name"`
	Executor     string `json:"executor"`
	Duty         string `json:"duty,omitempty"`
	DutyPreview  string `json:"dutyPreview,omitempty"`
	State        string `json:"state"`
	WorkID       string `json:"workId"`
	TaskID       string `json:"taskId"`
	TaskRevision int    `json:"taskRevision"`
	RoundCount   int    `json:"roundCount"`
	MemoryPath   string `json:"memoryPath"`
}
type snapshot struct {
	ID                 string          `json:"id"`
	Name               string          `json:"name"`
	Goal               string          `json:"goal"`
	MainConversationID string          `json:"mainConversationId"`
	MainState          string          `json:"mainState"`
	Revision           int             `json:"revision"`
	Sequence           int64           `json:"sequence"`
	Paused             bool            `json:"paused"`
	Archived           bool            `json:"archived"`
	State              string          `json:"state"`
	Target             json.RawMessage `json:"target"`
	Members            []member        `json:"members"`
	Work               []workItem      `json:"work"`
	Posts              []post          `json:"posts"`
	MainMessages       []mainMessage   `json:"mainMessages"`
}

func swarmPath(id string) (string, error) {
	if !managedID.MatchString(id) {
		return "", fmt.Errorf("managed swarm ID required (sw-...)")
	}
	return "/v1/swarms/" + url.PathEscape(id), nil
}
func readSnapshot(ctx context.Context, client *runtimeClient, path string) (snapshot, json.RawMessage, error) {
	raw, err := client.request(ctx, "GET", path, nil)
	if err != nil {
		return snapshot{}, nil, err
	}
	var value snapshot
	err = responseData(raw, &value)
	if err == nil && value.ID == "" {
		err = fmt.Errorf("INVALID_SWARM_RESPONSE")
	}
	return value, raw, err
}
func findWork(value snapshot, selector string) (workItem, error) {
	var found []workItem
	for _, work := range value.Work {
		if work.ID == selector || work.MemberID == selector || work.Member == selector {
			found = append(found, work)
		}
	}
	if len(found) == 0 {
		return workItem{}, fmt.Errorf("SWARM_MEMBER_TASK_REQUIRED: %s", selector)
	}
	if len(found) > 1 {
		return workItem{}, fmt.Errorf("ambiguous member: %s; use --file with an explicit workId", selector)
	}
	return found[0], nil
}
func boardColumn(state string) string {
	switch state {
	case "succeeded", "done":
		return "done"
	case "failed", "blocked", "unknown", "interrupted", "cancelled":
		return "blocked"
	case "waiting_user", "verifying", "review":
		return "review"
	case "running", "preparing", "cancelling":
		return "doing"
	default:
		return "backlog"
	}
}
