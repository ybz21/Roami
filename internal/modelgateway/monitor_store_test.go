package modelgateway

import (
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

func TestMonitorRingRetentionCapacityRestartAndCorruption(t *testing.T) {
	now := time.Date(2026, 11, 12, 12, 0, 0, 0, time.UTC)
	path := filepath.Join(t.TempDir(), "monitor.ring")
	clock := func() time.Time { return now }
	store, err := openMonitorStore(path, 3, clock)
	if err != nil {
		t.Fatal(err)
	}
	for index := 0; index < 5; index++ {
		if err = store.Append(MonitorRecord{At: now.Add(time.Duration(index) * time.Millisecond).UnixMilli(), SourceID: "s", Model: "m", Success: true, Quality: "unchecked"}); err != nil {
			t.Fatal(err)
		}
	}
	rows, stats, err := store.Snapshot()
	if err != nil || len(rows) != 3 || stats["evicted"] != uint64(2) {
		t.Fatalf("capacity: %v %v", stats, err)
	}
	info, _ := os.Stat(path)
	if info.Size() != 3*monitorSlotBytes || info.Size() > monitorDiskBudget {
		t.Fatal("unbounded file")
	}
	_ = store.Close()
	store, err = openMonitorStore(path, 3, clock)
	if err != nil {
		t.Fatal(err)
	}
	rows, _, _ = store.Snapshot()
	if len(rows) != 3 {
		t.Fatal("restart lost records")
	}
	now = now.Add(24*time.Hour + time.Second)
	if err = store.Maintain(); err != nil {
		t.Fatal(err)
	}
	rows, _, _ = store.Snapshot()
	if len(rows) != 0 {
		t.Fatal("expired records retained")
	}
	_ = store.Close()
	store, err = openMonitorStore(path, 3, clock)
	if err != nil {
		t.Fatal(err)
	}
	if err = store.Append(MonitorRecord{SourceID: "s", Model: "m", Quality: "pass"}); err != nil {
		t.Fatal(err)
	}
	_ = store.Close()
	file, _ := os.OpenFile(path, os.O_RDWR, 0600)
	_, _ = file.WriteAt([]byte("corrupt"), 8)
	_ = file.Close()
	store, err = openMonitorStore(path, 3, clock)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	rows, _, _ = store.Snapshot()
	if len(rows) != 0 {
		t.Fatal("corrupt CRC accepted")
	}
}
func TestMonitorRingConcurrentWritesAndQualityUnknowns(t *testing.T) {
	store, err := openMonitorStore(filepath.Join(t.TempDir(), "monitor.ring"), 20, time.Now)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	var wait sync.WaitGroup
	for i := 0; i < 100; i++ {
		wait.Add(1)
		go func() {
			defer wait.Done()
			if err := store.Append(MonitorRecord{SourceID: "s", Model: "m", Success: true, Quality: "unchecked"}); err != nil {
				t.Error(err)
			}
		}()
	}
	wait.Wait()
	rows, stats, err := store.Snapshot()
	if err != nil || len(rows) != 20 || stats["evicted"] != uint64(80) {
		t.Fatalf("concurrent capacity: %v %v", stats, err)
	}
	totals := summarizeMonitor([]MonitorRecord{{Success: true, FirstToken: routeNumber(100), Quality: "unchecked"}, {Success: true, FirstToken: routeNumber(200), Quality: "fail"}, {Success: false, Quality: "unchecked"}})
	if totals.Quality == nil || *totals.Quality != 0 || totals.Graded != 1 || totals.FirstTokenP95 == nil || *totals.FirstTokenP95 != 200 {
		t.Fatalf("monitor quality: %+v", totals)
	}
	if summarizeMonitor(nil).Quality != nil {
		t.Fatal("unknown quality became zero")
	}
}
