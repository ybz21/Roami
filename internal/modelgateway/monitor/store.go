package monitor

import (
	"encoding/binary"
	"encoding/json"
	"errors"
	"hash/crc32"
	"io"
	"math"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"sync"
	"time"

	"golang.org/x/sys/unix"
)

const monitorRetention = 24 * time.Hour
const DefaultCapacity = 10000
const monitorSlotBytes = 4096
const monitorDiskBudget = 64 << 20

type TokenUsage struct {
	Input  int64 `json:"input"`
	Output int64 `json:"output"`
}

type Record struct {
	Sequence        uint64         `json:"sequence"`
	At              int64          `json:"at"`
	SourceID        string         `json:"sourceId"`
	Model           string         `json:"model"`
	RouteID         string         `json:"routeId,omitempty"`
	Account         string         `json:"account,omitempty"`
	Success         bool           `json:"success"`
	Status          int            `json:"status"`
	Error           string         `json:"error,omitempty"`
	Duration        int64          `json:"durationMs"`
	FirstToken      *float64       `json:"firstTokenMs"`
	TokensPerSecond *float64       `json:"tokensPerSecond"`
	Quality         string         `json:"quality"`
	QualityRule     string         `json:"qualityRule,omitempty"`
	RequestID       string         `json:"requestId,omitempty"`
	CallID          string         `json:"callId,omitempty"`
	Outcome         string         `json:"outcome,omitempty"`
	Caller          string         `json:"caller,omitempty"`
	Revision        string         `json:"revision,omitempty"`
	UpstreamModel   string         `json:"upstreamModel,omitempty"`
	Attempts        int            `json:"attempts,omitempty"`
	Attempt         int            `json:"attempt,omitempty"`
	Switch          string         `json:"switch,omitempty"`
	Blocks          map[string]int `json:"blocks,omitempty"`
	GroupPath       []string       `json:"groupPath,omitempty"`

	TokenUsage *TokenUsage `json:"tokenUsage,omitempty"`
}
type Store struct {
	mu                        sync.Mutex
	file                      *os.File
	records                   map[int]Record
	sequence                  uint64
	capacity                  int
	expired, evicted, dropped uint64
	now                       func() time.Time
}

func Open(path string, capacity int, now func() time.Time) (*Store, error) {
	if capacity < 1 || capacity > DefaultCapacity {
		return nil, errors.New("INVALID_MONITOR_CAPACITY")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return nil, err
	}
	fd, err := unix.Open(path, unix.O_CREAT|unix.O_RDWR|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0600)
	if err != nil {
		return nil, err
	}
	file := os.NewFile(uintptr(fd), path)
	fail := func(err error) (*Store, error) { file.Close(); return nil, err }
	info, err := file.Stat()
	if err != nil {
		return fail(err)
	}
	if !info.Mode().IsRegular() {
		return fail(errors.New("INVALID_MONITOR_FILE"))
	}
	if err = file.Chmod(0600); err != nil {
		return fail(err)
	}
	if err = file.Truncate(int64(capacity * monitorSlotBytes)); err != nil {
		return fail(err)
	}
	store := &Store{file: file, records: map[int]Record{}, capacity: capacity, now: now}
	buffer := make([]byte, monitorSlotBytes)
	for slot := 0; slot < capacity; slot++ {
		if _, err = file.ReadAt(buffer, int64(slot*monitorSlotBytes)); err != nil && err != io.EOF {
			return fail(err)
		}
		size := int(binary.LittleEndian.Uint32(buffer))
		if size < 1 || size > monitorSlotBytes-8 {
			continue
		}
		raw := buffer[8 : 8+size]
		if crc32.ChecksumIEEE(raw) != binary.LittleEndian.Uint32(buffer[4:]) {
			continue
		}
		var record Record
		if json.Unmarshal(raw, &record) != nil || !validMonitorRecord(record) {
			continue
		}
		if record.Sequence > store.sequence {
			store.sequence = record.Sequence
		}
		store.records[slot] = record
	}
	if err = store.pruneLocked(now()); err != nil {
		return fail(err)
	}
	return store, nil
}
func validMonitorRecord(record Record) bool {
	if usage := record.TokenUsage; usage != nil && (usage.Input < 0 || usage.Input > 100_000_000 || usage.Output < 0 || usage.Output > 100_000_000) {
		return false
	}
	return record.Sequence > 0 && len(record.RequestID) <= 36 && len(record.CallID) <= 36 && len(record.Caller) <= 120 && len(record.Revision) <= 160 && len(record.UpstreamModel) <= 200 && record.At > 0 && len(record.SourceID) <= 160 && len(record.Model) <= 200 && len(record.RouteID) <= 160 && len(record.Account) <= 200 && len(record.Error) <= 100 && record.Duration >= 0 && slices.Contains([]string{"pass", "fail", "unchecked"}, record.Quality) && (record.FirstToken == nil || !math.IsNaN(*record.FirstToken) && !math.IsInf(*record.FirstToken, 0) && *record.FirstToken >= 0) && (record.TokensPerSecond == nil || !math.IsNaN(*record.TokensPerSecond) && !math.IsInf(*record.TokensPerSecond, 0) && *record.TokensPerSecond >= 0)
}
func (s *Store) pruneLocked(now time.Time) error {
	for slot, record := range s.records {
		if record.At <= now.Add(-monitorRetention).UnixMilli() || record.At > now.Add(time.Minute).UnixMilli() {
			if _, err := s.file.WriteAt(make([]byte, monitorSlotBytes), int64(slot*monitorSlotBytes)); err != nil {
				return err
			}
			delete(s.records, slot)
			s.expired++
		}
	}
	return nil
}
func (s *Store) Append(record Record) error {
	if s == nil {
		return nil
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	now := s.now()
	if err := s.pruneLocked(now); err != nil {
		s.dropped++
		return err
	}
	s.sequence++
	record.Sequence = s.sequence
	if record.At == 0 {
		record.At = now.UnixMilli()
	}
	if !validMonitorRecord(record) || record.At <= now.Add(-monitorRetention).UnixMilli() || record.At > now.Add(time.Minute).UnixMilli() {
		s.dropped++
		return errors.New("INVALID_MONITOR_RECORD")
	}
	raw, err := json.Marshal(record)
	if err != nil || len(raw) > monitorSlotBytes-8 {
		s.dropped++
		return errors.New("MONITOR_RECORD_TOO_LARGE")
	}
	slot := int((s.sequence - 1) % uint64(s.capacity))
	if _, exists := s.records[slot]; exists {
		s.evicted++
	}
	buffer := make([]byte, monitorSlotBytes)
	binary.LittleEndian.PutUint32(buffer, uint32(len(raw)))
	binary.LittleEndian.PutUint32(buffer[4:], crc32.ChecksumIEEE(raw))
	copy(buffer[8:], raw)
	if _, err = s.file.WriteAt(buffer, int64(slot*monitorSlotBytes)); err != nil {
		s.dropped++
		return err
	}
	s.records[slot] = record
	return nil
}
func (s *Store) Maintain() error {
	if s == nil {
		return nil
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.pruneLocked(s.now()); err != nil {
		return err
	}
	return s.file.Sync()
}
func (s *Store) Close() error {
	if s == nil {
		return nil
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	_ = s.file.Sync()
	return s.file.Close()
}
func (s *Store) Snapshot() (records []Record, storage map[string]any, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err = s.pruneLocked(s.now()); err != nil {
		return
	}
	records = make([]Record, 0, len(s.records))
	for _, record := range s.records {
		records = append(records, record)
	}
	sort.Slice(records, func(i, j int) bool {
		return records[i].At < records[j].At || records[i].At == records[j].At && records[i].Sequence < records[j].Sequence
	})
	info, e := s.file.Stat()
	if e != nil {
		err = e
		return
	}
	storage = map[string]any{"records": len(records), "maxRecords": s.capacity, "bytes": info.Size(), "maxBytes": monitorDiskBudget, "retentionHours": 24, "expired": s.expired, "evicted": s.evicted, "dropped": s.dropped}
	return
}
func ErrorCode(code string) string {
	if len(code) > 100 {
		return "MODEL_GATEWAY_FAILED"
	}
	for _, c := range code {
		if !(c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_') {
			return "MODEL_GATEWAY_FAILED"
		}
	}
	return strings.TrimSpace(code)
}

func (s *Store) Now() time.Time { return s.now() }
