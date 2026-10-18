package agentexecution

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type MessageSpec struct {
	Key       string `json:"key"`
	SessionID string `json:"sessionId"`
	Text      string `json:"text"`
}
type MessageReceipt struct {
	Key              string `json:"key"`
	Session          string `json:"session"`
	State            string `json:"state"`
	OutcomeKnown     bool   `json:"outcomeKnown"`
	ExecutionTracked bool   `json:"executionTracked"`
	SentMS           int64  `json:"sentMs,omitempty"`
}
type savedMessage struct {
	Digest  string         `json:"digest"`
	Receipt MessageReceipt `json:"receipt"`
}

// SendMessage acknowledges submission only; it never infers execution completion from a pane.
func (s Service) SendMessage(spec MessageSpec) (MessageReceipt, error) {
	if spec.Key == "" || len(spec.Key) > 250 || strings.TrimSpace(spec.Text) == "" || len(spec.Text) > 100000 || spec.SessionID == "" {
		return MessageReceipt{}, fmt.Errorf("INVALID_SESSION_MESSAGE")
	}
	dir, err := s.directory("message:" + spec.Key)
	if err != nil {
		return MessageReceipt{}, err
	}
	if err = os.MkdirAll(dir, 0700); err != nil {
		return MessageReceipt{}, err
	}
	unlock, err := lock(filepath.Join(dir, "message.lock"))
	if err != nil {
		return MessageReceipt{}, err
	}
	defer unlock()
	digest := sha256.Sum256([]byte(spec.SessionID + "\x00" + spec.Text))
	hash := hex.EncodeToString(digest[:])
	path := filepath.Join(dir, "message.json")
	var prior savedMessage
	if err = readJSON(path, &prior); err == nil {
		if prior.Digest != hash {
			return MessageReceipt{}, fmt.Errorf("MESSAGE_KEY_CONFLICT")
		}
		return prior.Receipt, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return MessageReceipt{}, err
	}
	binding, err := s.paneBinding(spec.SessionID, false)
	if err != nil {
		return MessageReceipt{}, err
	}
	receipt := MessageReceipt{Key: spec.Key, Session: binding.ID, State: "unknown"}
	if err = writeJSON(path, savedMessage{Digest: hash, Receipt: receipt}); err != nil {
		return MessageReceipt{}, err
	}
	// Persist uncertainty before input: a crash or partial paste must never trigger an automatic replay.
	if err = s.Runtime.SendPromptSubmit(binding.Pane, spec.Text); err != nil {
		return receipt, nil
	}
	receipt.State = "delivered"
	receipt.OutcomeKnown = true
	receipt.SentMS = time.Now().UnixMilli()
	if err = writeJSON(path, savedMessage{Digest: hash, Receipt: receipt}); err != nil {
		return MessageReceipt{}, err
	}
	return receipt, nil
}
