// Package sessionlifecycle persists ordinary session resource operations, independently of business tasks.
package sessionlifecycle

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"time"
)

var ErrConflict = errors.New("LIFECYCLE_REVISION_CHANGED")
var ErrRequestKey = errors.New("LIFECYCLE_REQUEST_KEY_REUSED")

type Database interface {
	Tx(func(*sql.Tx) error) error
	Query(string, ...any) (*sql.Rows, error)
	QueryRow(string, ...any) *sql.Row
}

type Intent struct {
	Name            string  `json:"name,omitempty"`
	Task            string  `json:"task,omitempty"`
	Dir             string  `json:"dir,omitempty"`
	Parent          string  `json:"parent,omitempty"`
	ParentIdentity  string  `json:"parentIdentity,omitempty"`
	Worktree        bool    `json:"worktree,omitempty"`
	Branch          string  `json:"branch,omitempty"`
	Base            string  `json:"base,omitempty"`
	Remote          string  `json:"remote,omitempty"`
	Existing        bool    `json:"existing,omitempty"`
	Mode            string  `json:"mode,omitempty"`
	Path            string  `json:"path,omitempty"`
	Strategy        string  `json:"strategy,omitempty"`
	KeepBranch      bool    `json:"keepBranch,omitempty"`
	Snapshot        string  `json:"snapshot,omitempty"`
	SessionIdentity string  `json:"sessionIdentity,omitempty"`
	Launch          *Launch `json:"launch,omitempty"`
}

// Prompt templates are filled as text before shell quoting; paths never become shell syntax.
type Launch struct {
	Command      string `json:"command"`
	Agent        string `json:"agent"`
	Task         string `json:"task"`
	Preamble     string `json:"preamble"`
	TaskHeading  string `json:"taskHeading"`
	SetupHeading string `json:"setupHeading"`
	FileBase     string `json:"fileBase"`
	AutoReview   bool   `json:"autoReview"`
}

type Operation struct {
	ID              string                     `json:"operationId"`
	RequestKey      string                     `json:"requestKey"`
	Digest          string                     `json:"-"`
	ResourceID      string                     `json:"resourceId"`
	Kind            string                     `json:"kind"`
	Intent          Intent                     `json:"intent"`
	OriginalIntent  Intent                     `json:"originalIntent"`
	State           string                     `json:"state"`
	Stage           string                     `json:"stage"`
	Revision        int64                      `json:"revision"`
	Epoch           int64                      `json:"epoch"`
	CancelRequested bool                       `json:"cancelRequested"`
	Receipts        map[string]json.RawMessage `json:"receipts"`
	ErrorCode       string                     `json:"errorCode,omitempty"`
	ErrorDetail     string                     `json:"errorDetail,omitempty"`
	AcceptedAt      int64                      `json:"acceptedAt"`
	UpdatedAt       int64                      `json:"updatedAt"`
}

func (o Operation) Terminal() bool        { return o.State == "succeeded" || o.State == "cancelled" }
func (o Operation) Has(stage string) bool { _, ok := o.Receipts[stage]; return ok }
func (o Operation) Receipt(stage string, value any) error {
	return json.Unmarshal(o.Receipts[stage], value)
}

type Store struct {
	DB      Database
	LockDir string
}

func New(db Database, databasePath string) *Store {
	return &Store{DB: db, LockDir: databasePath + ".lifecycle-locks"}
}

const columns = `id,request_key,digest,resource_id,kind,intent,original_intent,state,stage,revision,epoch,cancel_requested,receipts,error_code,error_detail,accepted_at,updated_at`

type scanner interface{ Scan(...any) error }

func scan(s scanner) (o Operation, err error) {
	var intent, original, receipts string
	err = s.Scan(&o.ID, &o.RequestKey, &o.Digest, &o.ResourceID, &o.Kind, &intent, &original, &o.State, &o.Stage, &o.Revision, &o.Epoch, &o.CancelRequested, &receipts, &o.ErrorCode, &o.ErrorDetail, &o.AcceptedAt, &o.UpdatedAt)
	if err != nil {
		return
	}
	if err = json.Unmarshal([]byte(intent), &o.Intent); err != nil {
		return
	}
	if err = json.Unmarshal([]byte(original), &o.OriginalIntent); err != nil {
		return
	}
	err = json.Unmarshal([]byte(receipts), &o.Receipts)
	return
}

func (s *Store) Get(id string) (Operation, error) {
	return scan(s.DB.QueryRow("SELECT "+columns+" FROM session_lifecycle_operations WHERE id=?", id))
}
func (s *Store) ByKey(key string) (Operation, error) {
	return scan(s.DB.QueryRow("SELECT "+columns+" FROM session_lifecycle_operations WHERE request_key=?", key))
}
func (s *Store) List() ([]Operation, error) {
	rows, err := s.DB.Query("SELECT " + columns + " FROM session_lifecycle_operations WHERE state NOT IN ('succeeded','cancelled') OR id IN (SELECT id FROM session_lifecycle_operations ORDER BY accepted_at DESC LIMIT 100) ORDER BY accepted_at DESC")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []Operation{}
	for rows.Next() {
		o, e := scan(rows)
		if e != nil {
			return nil, e
		}
		result = append(result, o)
	}
	return result, rows.Err()
}

func event(tx *sql.Tx, o Operation) error {
	summary, _ := json.Marshal(map[string]any{"mode": o.Intent.Mode, "errorCode": o.ErrorCode, "epoch": o.Epoch, "stopped": o.Has("stop"), "removed": o.Has("remove"), "keepBranch": o.Intent.KeepBranch})
	_, err := tx.Exec(`INSERT INTO session_lifecycle_events(operation_id,revision,state,stage,at,summary) VALUES(?,?,?,?,?,?)`, o.ID, o.Revision, o.State, o.Stage, o.UpdatedAt, string(summary))
	return err
}

func (s *Store) Accept(id, resource, key, kind string, intent Intent) (Operation, error) {
	requestIntent := intent
	requestIntent.ParentIdentity = ""
	payload, err := json.Marshal(struct {
		Kind   string
		Intent Intent
	}{kind, requestIntent})
	if err != nil {
		return Operation{}, err
	}
	digest := fmt.Sprintf("%x", sha256.Sum256(payload))
	var result Operation
	err = s.DB.Tx(func(tx *sql.Tx) error {
		old, e := scan(tx.QueryRow("SELECT "+columns+" FROM session_lifecycle_operations WHERE request_key=?", key))
		if e == nil {
			if old.Digest != digest {
				return ErrRequestKey
			}
			result = old
			return nil
		}
		if !errors.Is(e, sql.ErrNoRows) {
			return e
		}
		if kind == "close" {
			var n int
			if e = tx.QueryRow(`SELECT count(*) FROM session_lifecycle_operations WHERE resource_id=? AND state NOT IN ('succeeded','cancelled')`, resource).Scan(&n); e != nil {
				return e
			}
			if n > 0 {
				return ErrConflict
			}
		}
		now := time.Now().UnixMilli()
		result = Operation{ID: id, RequestKey: key, Digest: digest, ResourceID: resource, Kind: kind, Intent: intent, OriginalIntent: intent, State: "queued", Stage: "accepted", Revision: 1, Receipts: map[string]json.RawMessage{}, AcceptedAt: now, UpdatedAt: now}
		encoded, _ := json.Marshal(intent)
		_, e = tx.Exec(`INSERT INTO session_lifecycle_operations(id,request_key,digest,resource_id,kind,intent,original_intent,state,accepted_at,updated_at) VALUES(?,?,?,?,?,?,?,'queued',?,?)`, id, key, digest, resource, kind, string(encoded), string(encoded), now, now)
		if e != nil {
			return e
		}
		return event(tx, result)
	})
	return result, err
}

// Mutate serializes checkpoints, user actions and worker claims in one transaction.
func (s *Store) Mutate(id string, revision int64, fn func(*Operation) error) (Operation, error) {
	return s.mutate(id, revision, "", "", fn)
}

func (s *Store) Action(id, key, action string, revision int64, fn func(*Operation) error) (Operation, error) {
	return s.mutate(id, revision, key, fmt.Sprintf("%s:%d", action, revision), fn)
}

func (s *Store) mutate(id string, revision int64, key, digest string, fn func(*Operation) error) (Operation, error) {
	var result Operation
	err := s.DB.Tx(func(tx *sql.Tx) error {
		o, e := scan(tx.QueryRow("SELECT "+columns+" FROM session_lifecycle_operations WHERE id=?", id))
		if e != nil {
			return e
		}
		if key != "" {
			var owner, previous string
			err := tx.QueryRow("SELECT operation_id,digest FROM session_lifecycle_actions WHERE request_key=?", key).Scan(&owner, &previous)
			if err == nil {
				if owner != id || previous != digest {
					return ErrRequestKey
				}
				result = o
				return nil
			}
			if !errors.Is(err, sql.ErrNoRows) {
				return err
			}
		}
		if revision != o.Revision {
			return ErrConflict
		}
		if e = fn(&o); e != nil {
			return e
		}
		o.Revision++
		o.UpdatedAt = time.Now().UnixMilli()
		receipts, _ := json.Marshal(o.Receipts)
		intent, _ := json.Marshal(o.Intent)
		_, e = tx.Exec(`UPDATE session_lifecycle_operations SET state=?,stage=?,revision=?,epoch=?,cancel_requested=?,receipts=?,error_code=?,error_detail=?,updated_at=?,intent=? WHERE id=?`, o.State, o.Stage, o.Revision, o.Epoch, o.CancelRequested, string(receipts), o.ErrorCode, o.ErrorDetail, o.UpdatedAt, string(intent), o.ID)
		if e != nil {
			return e
		}
		result = o
		if key != "" {
			if _, e = tx.Exec("INSERT INTO session_lifecycle_actions(request_key,operation_id,digest) VALUES(?,?,?)", key, id, digest); e != nil {
				return e
			}
		}
		return event(tx, o)
	})
	return result, err
}

type operationContextKey struct{}

func WithOperation(ctx context.Context, id string) context.Context {
	return context.WithValue(ctx, operationContextKey{}, id)
}
func (s *Store) Check(ctx context.Context, resource, directory string) error {
	if directory != "" {
		directory = CanonicalPath(directory)
	}
	rows, err := s.DB.Query(`SELECT id,resource_id,kind,intent,state,receipts FROM session_lifecycle_operations WHERE state NOT IN ('succeeded','cancelled')`)
	if err != nil {
		return err
	}
	defer rows.Close()
	owner, _ := ctx.Value(operationContextKey{}).(string)
	for rows.Next() {
		var id, res, kind, raw, state, rawReceipts string
		if err = rows.Scan(&id, &res, &kind, &raw, &state, &rawReceipts); err != nil {
			return err
		}
		if id == owner {
			continue
		}
		var intent Intent
		if err = json.Unmarshal([]byte(raw), &intent); err != nil {
			return err
		}
		if resource != "" && resource == res {
			return fmt.Errorf("LIFECYCLE_RESOURCE_BUSY")
		}
		reserved := intent.Path
		if kind == "create" {
			var receipts map[string]json.RawMessage
			if err = json.Unmarshal([]byte(rawReceipts), &receipts); err != nil {
				return err
			}
			var planned struct {
				Path string `json:"path"`
			}
			if value := receipts["workspace-intent"]; len(value) > 0 {
				if err = json.Unmarshal(value, &planned); err != nil {
					return err
				}
				reserved = planned.Path
			}
		}
		if directory != "" && reserved != "" {
			rel, e := filepath.Rel(filepath.Clean(reserved), filepath.Clean(directory))
			if e == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
				return fmt.Errorf("LIFECYCLE_WORKSPACE_BUSY")
			}
		}
	}
	return rows.Err()
}

func CanonicalPath(path string) string {
	if resolved, err := filepath.EvalSymlinks(path); err == nil {
		return filepath.Clean(resolved)
	}
	return filepath.Clean(path)
}

func (s *Store) Pending(kind string) ([]string, error) {
	rows, err := s.DB.Query(`SELECT id FROM session_lifecycle_operations WHERE state IN ('queued','running') AND kind=? ORDER BY accepted_at`, kind)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var ids []string
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, rows.Err()
}
