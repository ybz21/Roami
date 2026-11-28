// Package sessioncoord owns the minimal, schema-frozen SQLite coordination database
// (session-host.db) shared by roami-term hosts and control-plane clients,
// completely isolated from main meta.db schema migrations and storage locks.
package sessioncoord

import (
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
	_ "modernc.org/sqlite"
)

const (
	HostStateReady    = "ready"
	HostStateActive   = "active"
	HostStateDraining = "draining"
	HostStateRetiring = "retiring"
	HostStateRetired  = "retired"

	OpStateAccepted  = "accepted"
	OpStateStarting  = "starting"
	OpStateSucceeded = "succeeded"
	OpStateFailed    = "failed"

	DefaultMaxDrainingHosts = 2
)

var (
	ErrOperationConflict = errors.New("OPERATION_DIGEST_CONFLICT")
	ErrHostNotReady      = errors.New("HOST_NOT_READY")
	ErrHostStillActive   = errors.New("HOST_STILL_ACTIVE")
)

type HostRecord struct {
	HostID        string `json:"hostId"`
	Version       string `json:"version"`
	ProtocolMin   int    `json:"protocolMin"`
	ProtocolMax   int    `json:"protocolMax"`
	Endpoint      string `json:"endpoint"`
	TokenPath     string `json:"tokenPath,omitempty"`
	PID           int    `json:"pid"`
	ProcessID     string `json:"processId,omitempty"`
	State         string `json:"state"`
	DrainingSince int64  `json:"drainingSince,omitempty"`
	UpdatedAt     int64  `json:"updatedAt"`
}

type HostPointer struct {
	CurrentHost string `json:"currentHost"`
	Generation  int64  `json:"generation"`
}

type OperationRecord struct {
	OperationID string `json:"operationId"`
	Digest      string `json:"digest"`
	HostID      string `json:"hostId"`
	Generation  int64  `json:"generation"`
	State       string `json:"state"`
	SessionID   string `json:"sessionId,omitempty"`
	ErrorCode   string `json:"errorCode,omitempty"`
	CreatedAt   int64  `json:"createdAt"`
	UpdatedAt   int64  `json:"updatedAt"`
}

type DB struct {
	db   *sql.DB
	path string
	mu   sync.Mutex
	now  func() time.Time
}

const coordSchema = `
CREATE TABLE IF NOT EXISTS host_registry (
	host_id        TEXT PRIMARY KEY,
	version        TEXT NOT NULL DEFAULT '',
	protocol_min   INTEGER NOT NULL DEFAULT 1,
	protocol_max   INTEGER NOT NULL DEFAULT 1,
	endpoint       TEXT NOT NULL DEFAULT '',
	token_path     TEXT NOT NULL DEFAULT '',
	pid            INTEGER NOT NULL DEFAULT 0,
	process_id     TEXT NOT NULL DEFAULT '',
	state          TEXT NOT NULL DEFAULT 'ready',
	draining_since INTEGER NOT NULL DEFAULT 0,
	updated_at     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS host_pointer (
	slot         INTEGER PRIMARY KEY CHECK(slot = 1),
	current_host TEXT NOT NULL DEFAULT '',
	generation   INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO host_pointer(slot, current_host, generation) VALUES(1, '', 0);
CREATE TABLE IF NOT EXISTS host_operations (
	operation_id TEXT PRIMARY KEY,
	digest       TEXT NOT NULL,
	host_id      TEXT NOT NULL,
	generation   INTEGER NOT NULL,
	state        TEXT NOT NULL,
	session_id   TEXT NOT NULL DEFAULT '',
	error_code   TEXT NOT NULL DEFAULT '',
	created_at   INTEGER NOT NULL,
	updated_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_host_operations_host_state ON host_operations(host_id, state);
`

func Open(path string) (*DB, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return nil, err
	}
	dsn := "file:" + path + "?_pragma=busy_timeout(10000)&_pragma=journal_mode(WAL)&_pragma=synchronous(NORMAL)&_txlock=immediate"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(4)
	db.SetMaxIdleConns(4)
	if _, err := db.Exec(coordSchema); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("sessioncoord: init schema: %w", err)
	}
	return &DB{db: db, path: path, now: time.Now}, nil
}

func (c *DB) Close() error { return c.db.Close() }

func (c *DB) tx(fn func(*sql.Tx) error) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	tx, err := c.db.Begin()
	if err != nil {
		return err
	}
	if err := fn(tx); err != nil {
		_ = tx.Rollback()
		return err
	}
	return tx.Commit()
}

func (c *DB) RegisterHost(rec HostRecord) error {
	now := c.now().UnixMilli()
	if rec.State == "" {
		rec.State = HostStateReady
	}
	if rec.ProtocolMin <= 0 {
		rec.ProtocolMin = 1
	}
	if rec.ProtocolMax < rec.ProtocolMin {
		rec.ProtocolMax = rec.ProtocolMin
	}
	return c.tx(func(tx *sql.Tx) error {
		_, err := tx.Exec(`INSERT INTO host_registry
			(host_id, version, protocol_min, protocol_max, endpoint, token_path, pid, process_id, state, draining_since, updated_at)
			VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
			ON CONFLICT(host_id) DO UPDATE SET
				version=excluded.version, protocol_min=excluded.protocol_min, protocol_max=excluded.protocol_max,
				endpoint=excluded.endpoint, token_path=excluded.token_path, pid=excluded.pid,
				process_id=excluded.process_id, updated_at=excluded.updated_at`,
			rec.HostID, rec.Version, rec.ProtocolMin, rec.ProtocolMax, rec.Endpoint, rec.TokenPath,
			rec.PID, rec.ProcessID, rec.State, rec.DrainingSince, now)
		return err
	})
}

func (c *DB) Pointer() (HostPointer, error) {
	var p HostPointer
	err := c.db.QueryRow(`SELECT current_host, generation FROM host_pointer WHERE slot=1`).Scan(&p.CurrentHost, &p.Generation)
	return p, err
}

func (c *DB) Host(hostID string) (HostRecord, error) {
	var r HostRecord
	err := c.db.QueryRow(`SELECT host_id, version, protocol_min, protocol_max, endpoint, token_path, pid, process_id, state, draining_since, updated_at
		FROM host_registry WHERE host_id=?`, hostID).
		Scan(&r.HostID, &r.Version, &r.ProtocolMin, &r.ProtocolMax, &r.Endpoint, &r.TokenPath, &r.PID, &r.ProcessID, &r.State, &r.DrainingSince, &r.UpdatedAt)
	return r, err
}

func (c *DB) ListHosts() ([]HostRecord, error) {
	rows, err := c.db.Query(`SELECT host_id, version, protocol_min, protocol_max, endpoint, token_path, pid, process_id, state, draining_since, updated_at
		FROM host_registry ORDER BY updated_at DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []HostRecord
	for rows.Next() {
		var r HostRecord
		if err := rows.Scan(&r.HostID, &r.Version, &r.ProtocolMin, &r.ProtocolMax, &r.Endpoint, &r.TokenPath, &r.PID, &r.ProcessID, &r.State, &r.DrainingSince, &r.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// SwitchHost atomically updates (current_host, generation) via CAS while enforcing maxDraining.
func (c *DB) SwitchHost(targetHostID, expectedHost string, expectedGen int64, maxDraining int) (HostPointer, error) {
	if maxDraining <= 0 {
		maxDraining = DefaultMaxDrainingHosts
	}
	now := c.now().UnixMilli()
	var next HostPointer
	err := c.tx(func(tx *sql.Tx) error {
		var curHost string
		var curGen int64
		if err := tx.QueryRow(`SELECT current_host, generation FROM host_pointer WHERE slot=1`).Scan(&curHost, &curGen); err != nil {
			return err
		}
		if curGen != expectedGen || (expectedHost != "" && curHost != expectedHost) {
			return sessionbackend.ErrStaleGeneration
		}
		var targetState string
		if err := tx.QueryRow(`SELECT state FROM host_registry WHERE host_id=?`, targetHostID).Scan(&targetState); err != nil {
			return ErrHostNotReady
		}
		if targetState != HostStateReady && targetState != HostStateDraining && targetState != HostStateActive {
			return ErrHostNotReady
		}

		if curHost != "" && curHost != targetHostID {
			var draining int
			if err := tx.QueryRow(`SELECT count(*) FROM host_registry WHERE state=? AND host_id<>?`, HostStateDraining, targetHostID).Scan(&draining); err != nil {
				return err
			}
			if draining+1 > maxDraining {
				return sessionbackend.ErrDrainingCap
			}
			if _, err := tx.Exec(`UPDATE host_registry SET state=?, draining_since=CASE WHEN draining_since=0 THEN ? ELSE draining_since END, updated_at=? WHERE host_id=?`,
				HostStateDraining, now, now, curHost); err != nil {
				return err
			}
		}

		nextGen := curGen + 1
		if _, err := tx.Exec(`UPDATE host_registry SET state=?, draining_since=0, updated_at=? WHERE host_id=?`, HostStateActive, now, targetHostID); err != nil {
			return err
		}
		if _, err := tx.Exec(`UPDATE host_pointer SET current_host=?, generation=? WHERE slot=1`, targetHostID, nextGen); err != nil {
			return err
		}
		next = HostPointer{CurrentHost: targetHostID, Generation: nextGen}
		return nil
	})
	return next, err
}

// AdmitCreate serializes operation admission against host pointer switches.
func (c *DB) AdmitCreate(operationID, digest, hostID string, expectedGen int64) (OperationRecord, bool, error) {
	now := c.now().UnixMilli()
	var rec OperationRecord
	var existed bool
	err := c.tx(func(tx *sql.Tx) error {
		err := tx.QueryRow(`SELECT operation_id, digest, host_id, generation, state, session_id, error_code, created_at, updated_at
			FROM host_operations WHERE operation_id=?`, operationID).
			Scan(&rec.OperationID, &rec.Digest, &rec.HostID, &rec.Generation, &rec.State, &rec.SessionID, &rec.ErrorCode, &rec.CreatedAt, &rec.UpdatedAt)
		if err == nil {
			if rec.Digest != digest {
				return ErrOperationConflict
			}
			existed = true
			return nil
		}
		if !errors.Is(err, sql.ErrNoRows) {
			return err
		}

		var curHost string
		var curGen int64
		if err := tx.QueryRow(`SELECT current_host, generation FROM host_pointer WHERE slot=1`).Scan(&curHost, &curGen); err != nil {
			return err
		}
		if curHost != hostID || (expectedGen > 0 && curGen != expectedGen) {
			return sessionbackend.ErrStaleGeneration
		}
		rec = OperationRecord{
			OperationID: operationID,
			Digest:      digest,
			HostID:      hostID,
			Generation:  curGen,
			State:       OpStateAccepted,
			CreatedAt:   now,
			UpdatedAt:   now,
		}
		_, err = tx.Exec(`INSERT INTO host_operations(operation_id, digest, host_id, generation, state, session_id, error_code, created_at, updated_at)
			VALUES(?, ?, ?, ?, ?, '', '', ?, ?)`,
			rec.OperationID, rec.Digest, rec.HostID, rec.Generation, rec.State, rec.CreatedAt, rec.UpdatedAt)
		return err
	})
	return rec, existed, err
}

func (c *DB) ClaimStart(operationID, hostID string) (bool, error) {
	now := c.now().UnixMilli()
	var claimed bool
	err := c.tx(func(tx *sql.Tx) error {
		res, err := tx.Exec(`UPDATE host_operations SET state=?, updated_at=? WHERE operation_id=? AND host_id=? AND state=?`,
			OpStateStarting, now, operationID, hostID, OpStateAccepted)
		if err != nil {
			return err
		}
		n, _ := res.RowsAffected()
		claimed = n == 1
		return nil
	})
	return claimed, err
}

func (c *DB) CompleteOperation(operationID, sessionID, errCode string) error {
	now := c.now().UnixMilli()
	state := OpStateSucceeded
	if errCode != "" {
		state = OpStateFailed
	}
	return c.tx(func(tx *sql.Tx) error {
		_, err := tx.Exec(`UPDATE host_operations SET state=?, session_id=?, error_code=?, updated_at=? WHERE operation_id=?`,
			state, sessionID, errCode, now, operationID)
		return err
	})
}

func (c *DB) Operation(operationID string) (OperationRecord, error) {
	var rec OperationRecord
	err := c.db.QueryRow(`SELECT operation_id, digest, host_id, generation, state, session_id, error_code, created_at, updated_at
		FROM host_operations WHERE operation_id=?`, operationID).
		Scan(&rec.OperationID, &rec.Digest, &rec.HostID, &rec.Generation, &rec.State, &rec.SessionID, &rec.ErrorCode, &rec.CreatedAt, &rec.UpdatedAt)
	return rec, err
}

func (c *DB) PendingOperations(hostID string) (int, error) {
	var n int
	err := c.db.QueryRow(`SELECT count(*) FROM host_operations WHERE host_id=? AND state IN (?, ?)`,
		hostID, OpStateAccepted, OpStateStarting).Scan(&n)
	return n, err
}

func (c *DB) MarkRetiring(hostID string) error {
	now := c.now().UnixMilli()
	return c.tx(func(tx *sql.Tx) error {
		var curHost string
		if err := tx.QueryRow(`SELECT current_host FROM host_pointer WHERE slot=1`).Scan(&curHost); err != nil {
			return err
		}
		if curHost == hostID {
			return ErrHostStillActive
		}
		var pending int
		if err := tx.QueryRow(`SELECT count(*) FROM host_operations WHERE host_id=? AND state IN (?, ?)`,
			hostID, OpStateAccepted, OpStateStarting).Scan(&pending); err != nil {
			return err
		}
		if pending > 0 {
			return fmt.Errorf("host %s still has %d pending operations", hostID, pending)
		}
		_, err := tx.Exec(`UPDATE host_registry SET state=?, updated_at=? WHERE host_id=?`, HostStateRetiring, now, hostID)
		return err
	})
}

func (c *DB) MarkRetired(hostID string) error {
	now := c.now().UnixMilli()
	return c.tx(func(tx *sql.Tx) error {
		_, err := tx.Exec(`UPDATE host_registry SET state=?, updated_at=? WHERE host_id=?`, HostStateRetired, now, hostID)
		return err
	})
}
