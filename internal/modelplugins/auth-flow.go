package modelplugins

import (
	"context"
	"encoding/json"
	"errors"
	"time"
)

type AuthReply struct {
	Prompt       json.RawMessage `json:"prompt,omitempty"`
	Invalid      bool            `json:"invalid,omitempty"`
	OK           bool            `json:"ok"`
	Session      string          `json:"session,omitempty"`
	URL          string          `json:"url,omitempty"`
	Instructions string          `json:"instructions,omitempty"`
	Method       string          `json:"method,omitempty"`
	Error        string          `json:"error,omitempty"`
}
type authJob struct {
	SourceID string
	Cancel   context.CancelFunc
	Created  time.Time
	Done     bool
	OK       bool
}
type CallbackView struct {
	Done bool `json:"done"`
	OK   bool `json:"ok"`
}

func (m *Manager) BeginCallback(source Source, params map[string]any) (string, error) {
	if DesktopUnavailable(source.ProviderID) {
		return "", errors.New("MODEL_PLUGIN_DESKTOP_UNAVAILABLE")
	}
	id, err := freshID()
	if err != nil {
		return "", err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	m.mu.Lock()
	for key, job := range m.jobs {
		if job.Done && time.Since(job.Created) > 10*time.Minute {
			delete(m.jobs, key)
		}
	}
	for _, active := range m.jobs {
		if active.SourceID == source.ID && !active.Done {
			m.mu.Unlock()
			cancel()
			return "", errors.New("MODEL_PLUGIN_BUSY")
		}
	}
	if m.closed || len(m.jobs) >= 32 {
		m.mu.Unlock()
		cancel()
		return "", errors.New("MODEL_PLUGIN_BUSY")
	}
	job := &authJob{SourceID: source.ID, Cancel: cancel, Created: time.Now()}
	m.jobs[id] = job
	m.mu.Unlock()
	go func() {
		defer cancel()
		var reply AuthReply
		err := m.Auth(ctx, source, "callback", params, &reply)
		if err == nil && reply.OK {
			_, err = m.Provider(ctx, source)
		}
		m.mu.Lock()
		job.Done = true
		job.OK = err == nil && reply.OK
		m.mu.Unlock()
	}()
	return id, nil
}
func (m *Manager) CallbackStatus(source, id string, cancel bool) (CallbackView, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	job := m.jobs[id]
	if job == nil || job.SourceID != source {
		return CallbackView{}, errors.New("MODEL_PLUGIN_AUTH_NOT_FOUND")
	}
	if cancel {
		job.Cancel()
	}
	return CallbackView{Done: job.Done, OK: job.OK}, nil
}
func (m *Manager) Remove(id string) {
	if !sourceID.MatchString(id) {
		return
	}
	m.mu.Lock()
	for _, job := range m.jobs {
		if job.SourceID == id {
			job.Cancel()
		}
	}
	m.mu.Unlock()
	source, err := m.ReadSource(id)
	if err != nil {
		return
	}
	m.remove(source)
}
