package memalert

import (
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/storage"
)

func TestMemoryNoticesReachInboxAndDeduplicateTransitions(t *testing.T) {
	db, err := metadb.Open(t.TempDir(), metadb.Options{})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO sessions (id,status) VALUES ('okr','live')`); err != nil {
		t.Fatal(err)
	}
	samples := []Sample{{Session: "okr", Label: "OKR", Cur: 6 << 30, Limit: 10 << 30}}
	now := time.Now()
	Check(db, now, samples)
	Check(db, now, samples)
	samples[0].Paused = true
	Check(db, now, samples)
	Check(db, now, samples)
	var count int
	if err := db.QueryRow(`SELECT count(*) FROM plugin_notifications WHERE source='roam.web' AND type='session.memory'`).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != 2 {
		t.Fatalf("wanted warning and paused, got %d", count)
	}
	var body string
	if err := db.QueryRow(`SELECT body FROM plugin_notifications ORDER BY id DESC LIMIT 1`).Scan(&body); err != nil || body != "paused" {
		t.Fatalf("paused notice missing: %q %v", body, err)
	}
}

func TestFailedMemoryNoticeCanRetry(t *testing.T) {
	db, err := metadb.Open(t.TempDir(), metadb.Options{})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO sessions (id,status) VALUES ('retry','live');
		CREATE TRIGGER fail_memory_notice BEFORE INSERT ON plugin_notifications BEGIN SELECT RAISE(FAIL,'unavailable'); END`); err != nil {
		t.Fatal(err)
	}
	samples := []Sample{{Session: "retry", Warning: true}}
	Check(db, time.Now(), samples)
	if _, err := db.Exec(`DROP TRIGGER fail_memory_notice`); err != nil {
		t.Fatal(err)
	}
	Check(db, time.Now(), samples)
	var count int
	if err := db.QueryRow(`SELECT count(*) FROM plugin_notifications WHERE type='session.memory'`).Scan(&count); err != nil || count != 1 {
		t.Fatalf("failed notification was not retried: count=%d err=%v", count, err)
	}
}
