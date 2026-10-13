package api

import (
	"bufio"
	"encoding/json"
	"log"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type AIFootprint struct {
	At        int64 `json:"at"`
	Dialogues int   `json:"dialogues"`
	Tasks     int   `json:"tasks"`
}

type AIFootprintStore struct {
	mu     sync.Mutex
	file   string
	events []AIFootprint
	failed bool
}

func NewAIFootprintStore(dataDir string) *AIFootprintStore {
	s := &AIFootprintStore{file: filepath.Join(dataDir, "ai-footprints.jsonl"), events: []AIFootprint{}}
	if err := os.MkdirAll(dataDir, 0o755); err != nil {
		s.failed = true
	}
	f, err := os.Open(s.file)
	if os.IsNotExist(err) {
		return s
	}
	if err != nil {
		s.failed = true
		return s
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	cutoff := time.Now().AddDate(0, 0, -370).Unix()
	for scanner.Scan() {
		var event AIFootprint
		if err := json.Unmarshal(scanner.Bytes(), &event); err != nil {
			s.failed = true
			continue
		}
		if event.At >= cutoff {
			s.events = append(s.events, event)
		}
	}
	if scanner.Err() != nil {
		s.failed = true
	}
	return s
}

// Store counts only: prompts, responses, and session names never enter the activity log.
func (s *AIFootprintStore) Record(kind string, count int) {
	if s == nil || count <= 0 || (kind != "dialogue" && kind != "task") {
		return
	}
	event := AIFootprint{At: time.Now().Unix()}
	if kind == "dialogue" {
		event.Dialogues = count
	} else {
		event.Tasks = count
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	b, _ := json.Marshal(event)
	f, err := os.OpenFile(s.file, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err == nil {
		_, err = f.Write(append(b, '\n'))
		if err == nil {
			err = f.Sync()
		}
		closeErr := f.Close()
		if err == nil {
			err = closeErr
		}
	}
	if err != nil {
		s.failed = true
		log.Printf("AI footprints: persist counts: %v", err)
		return
	}
	s.events = append(s.events, event)
}

func (s *AIFootprintStore) Snapshot() ([]AIFootprint, bool) {
	if s == nil {
		return []AIFootprint{}, false
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	events := append([]AIFootprint{}, s.events...)
	return events, s.failed
}
