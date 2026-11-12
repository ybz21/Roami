package modelgateway

import (
	"encoding/binary"
	"encoding/json"
	"errors"
	"golang.org/x/sys/unix"
	"hash/crc32"
	"io"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

const monitorRetention = 24 * time.Hour
const monitorSlots = 10000
const monitorSlotBytes = 4096
const monitorDiskBudget = 64 << 20

type MonitorRecord struct {
	Sequence        uint64   `json:"sequence"`
	At              int64    `json:"at"`
	SourceID        string   `json:"sourceId"`
	Model           string   `json:"model"`
	RouteID         string   `json:"routeId,omitempty"`
	Account         string   `json:"account,omitempty"`
	Success         bool     `json:"success"`
	Status          int      `json:"status"`
	Error           string   `json:"error,omitempty"`
	Duration        int64    `json:"durationMs"`
	FirstToken      *float64 `json:"firstTokenMs"`
	TokensPerSecond *float64 `json:"tokensPerSecond"`
	Quality         string   `json:"quality"`
	QualityRule     string   `json:"qualityRule,omitempty"`
}
type MonitorStore struct {
	mu                        sync.Mutex
	file                      *os.File
	records                   map[int]MonitorRecord
	sequence                  uint64
	capacity                  int
	expired, evicted, dropped uint64
	now                       func() time.Time
}

func openMonitorStore(path string, capacity int, now func() time.Time) (*MonitorStore, error) {
	if capacity < 1 || capacity > monitorSlots {
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
	fail := func(err error) (*MonitorStore, error) { file.Close(); return nil, err }
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
	store := &MonitorStore{file: file, records: map[int]MonitorRecord{}, capacity: capacity, now: now}
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
		var record MonitorRecord
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
func validMonitorRecord(record MonitorRecord) bool {
	return record.Sequence > 0 && record.At > 0 && len(record.SourceID) <= 160 && len(record.Model) <= 200 && len(record.RouteID) <= 160 && len(record.Account) <= 200 && len(record.Error) <= 100 && record.Duration >= 0 && containsField([]string{"pass", "fail", "unchecked"}, record.Quality) && (record.FirstToken == nil || !math.IsNaN(*record.FirstToken) && !math.IsInf(*record.FirstToken, 0) && *record.FirstToken >= 0) && (record.TokensPerSecond == nil || !math.IsNaN(*record.TokensPerSecond) && !math.IsInf(*record.TokensPerSecond, 0) && *record.TokensPerSecond >= 0)
}
func (s *MonitorStore) pruneLocked(now time.Time) error {
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
func (s *MonitorStore) Append(record MonitorRecord) error {
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
func (s *MonitorStore) Maintain() error {
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
func (s *MonitorStore) Close() error {
	if s == nil {
		return nil
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	_ = s.file.Sync()
	return s.file.Close()
}
func (s *MonitorStore) Snapshot() (records []MonitorRecord, storage map[string]any, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err = s.pruneLocked(s.now()); err != nil {
		return
	}
	records = make([]MonitorRecord, 0, len(s.records))
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
func monitorError(code string) string {
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
