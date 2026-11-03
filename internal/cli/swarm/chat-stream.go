package swarm

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"
)

type chatMessage struct {
	ID            string `json:"id"`
	Author        string `json:"author"`
	Text          string `json:"text"`
	CreatedMS     int64  `json:"createdMs"`
	TaskID        string `json:"taskId,omitempty"`
	Revision      int    `json:"taskRevision,omitempty"`
	State         string `json:"state,omitempty"`
	DeliveryState string `json:"deliveryState,omitempty"`
}

func chatMessages(value snapshot) []chatMessage {
	messages := []chatMessage{}
	for _, post := range value.Posts {
		messages = append(messages, chatMessage{ID: fmt.Sprint("post:", post.ID), Author: post.Author, Text: post.Text, CreatedMS: post.CreatedMS, TaskID: post.TaskID, DeliveryState: post.DeliveryState})
	}
	for _, message := range value.MainMessages {
		if message.Text != "" {
			messages = append(messages, chatMessage{ID: "main:" + message.ID, Author: "main", Text: message.Text, CreatedMS: message.CreatedMS})
		}
	}
	for _, work := range value.Work {
		if work.Attempt != nil && work.Attempt.Summary != "" {
			messages = append(messages, chatMessage{ID: fmt.Sprintf("result:%s:%d", work.ID, work.Revision), Author: work.Member, Text: work.Attempt.Summary, CreatedMS: work.Attempt.FinishedMS, TaskID: work.TaskID, Revision: work.Revision, State: work.State})
		}
	}
	sort.SliceStable(messages, func(i, j int) bool { return messages[i].CreatedMS < messages[j].CreatedMS })
	return messages
}
func renderChat(w io.Writer, messages []chatMessage) error {
	for _, message := range messages {
		author := message.Author
		if author == "human" {
			author = "你"
		} else if author == "main" {
			author = "Roami Main"
		}
		stamp := ""
		if message.CreatedMS > 0 {
			stamp = time.UnixMilli(message.CreatedMS).Local().Format("01-02 15:04:05") + " "
		}
		detail := ""
		if message.State != "" {
			detail = " / " + stateLabel(message.State)
		}
		if message.DeliveryState == "pending" {
			detail += " / 等待投递确认"
		}
		if _, err := fmt.Fprintf(w, "\n%s%s%s\n%s\n", stamp, line(author), detail, message.Text); err != nil {
			return err
		}
	}
	return nil
}

type snapshotEvent struct {
	ID      int64           `json:"id"`
	Kind    string          `json:"kind"`
	Payload json.RawMessage `json:"payload"`
}

func consumeSnapshots(reader io.Reader, cursor *int64, groupID string, consume func(snapshot, snapshotEvent) error) error {
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 65536), responseLimit)
	data := []string{}
	flush := func() error {
		if len(data) == 0 {
			return nil
		}
		raw := strings.Join(data, "\n")
		data = nil
		var event snapshotEvent
		if err := json.Unmarshal([]byte(raw), &event); err != nil {
			return fmt.Errorf("invalid swarm event: %w", err)
		}
		if event.ID <= *cursor {
			return nil
		}
		if event.Kind != "swarm.snapshot" {
			return nil
		}
		var value snapshot
		if err := json.Unmarshal(event.Payload, &value); err != nil {
			return err
		}
		if value.ID != groupID {
			return fmt.Errorf("SWARM_EVENT_ID_MISMATCH")
		}
		if err := consume(value, event); err != nil {
			return err
		}
		*cursor = event.ID
		return nil
	}
	for scanner.Scan() {
		line := strings.TrimSuffix(scanner.Text(), "\r")
		if line == "" {
			if err := flush(); err != nil {
				return err
			}
			continue
		}
		if strings.HasPrefix(line, "data:") {
			data = append(data, strings.TrimPrefix(strings.TrimPrefix(line, "data:"), " "))
		}
	}
	if err := scanner.Err(); err != nil {
		return err
	}
	if err := flush(); err != nil {
		return err
	}
	return io.EOF
}
func followSnapshots(ctx context.Context, client *runtimeClient, path string, initial snapshot, consume func(snapshot, snapshotEvent) error) error {
	cursor := initial.Sequence
	delay := time.Second
	for {
		response, err := client.open(ctx, "GET", path+"/events?after="+url.QueryEscape(strconv.FormatInt(cursor, 10)), nil)
		before := cursor
		var renderError error
		if err == nil {
			if !strings.HasPrefix(response.Header.Get("Content-Type"), "text/event-stream") {
				response.Body.Close()
				return fmt.Errorf("INVALID_SWARM_EVENT_STREAM")
			}
			err = consumeSnapshots(response.Body, &cursor, initial.ID, func(value snapshot, event snapshotEvent) error {
				renderError = consume(value, event)
				return renderError
			})
			response.Body.Close()
		}
		if ctx.Err() != nil {
			return nil
		}
		if renderError != nil {
			return renderError
		}
		var rejection *runtimeError
		if errors.As(err, &rejection) && rejection.status < 500 {
			return err
		}
		if cursor > before {
			delay = time.Second
		}
		fmt.Fprintf(os.Stderr, "蜂群事件连接中断，%s 后重连；Ctrl-C 退出。\n", delay)
		timer := time.NewTimer(delay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return nil
		case <-timer.C:
		}
		delay = min(delay*2, 30*time.Second)
	}
}
func followChat(ctx context.Context, client *runtimeClient, path string, initial snapshot, limit int, w io.Writer, jsonOutput bool) error {
	messages := chatMessages(initial)
	seen := map[string]string{}
	for _, message := range messages {
		encoded, _ := json.Marshal(message)
		seen[message.ID] = string(encoded)
	}
	if len(messages) > limit {
		messages = messages[len(messages)-limit:]
	}
	if jsonOutput {
		if err := writeJSON(w, map[string]any{"kind": "swarm.chat", "id": initial.Sequence, "data": messages}); err != nil {
			return err
		}
	} else if err := renderChat(w, messages); err != nil {
		return err
	}
	return followSnapshots(ctx, client, path, initial, func(value snapshot, event snapshotEvent) error {
		for _, message := range chatMessages(value) {
			encoded, _ := json.Marshal(message)
			if seen[message.ID] == string(encoded) {
				continue
			}
			if jsonOutput {
				if err := writeJSON(w, map[string]any{"kind": "swarm.message", "id": event.ID, "data": message}); err != nil {
					return err
				}
			} else if err := renderChat(w, []chatMessage{message}); err != nil {
				return err
			}
			seen[message.ID] = string(encoded)
		}
		// Keep deduplication within the same bounded window as the service snapshot.
		current := map[string]string{}
		for _, message := range chatMessages(value) {
			current[message.ID] = seen[message.ID]
		}
		seen = current
		return nil
	})
}
func followView(ctx context.Context, client *runtimeClient, path string, initial snapshot, command string, w io.Writer, jsonOutput bool) error {
	writeView := func(value snapshot, sequence int64, raw json.RawMessage) error {
		var data any = raw
		if command == "board" {
			data = boardView(value)
		}
		return writeJSON(w, map[string]any{"id": sequence, "kind": "swarm." + command, "data": data})
	}
	if jsonOutput {
		raw, _ := json.Marshal(initial)
		if err := writeView(initial, initial.Sequence, raw); err != nil {
			return err
		}
	} else if err := renderSnapshot(w, initial, command, false); err != nil {
		return err
	}
	fingerprint := func(value snapshot) string {
		value.Posts = nil
		value.MainMessages = nil
		value.Sequence = 0
		raw, _ := json.Marshal(value)
		return string(raw)
	}
	previous := fingerprint(initial)
	return followSnapshots(ctx, client, path, initial, func(value snapshot, event snapshotEvent) error {
		current := fingerprint(value)
		if current == previous {
			return nil
		}
		if jsonOutput {
			if err := writeView(value, event.ID, event.Payload); err != nil {
				return err
			}
		} else if err := renderSnapshot(w, value, command, false); err != nil {
			return err
		}
		previous = current
		return nil
	})
}
