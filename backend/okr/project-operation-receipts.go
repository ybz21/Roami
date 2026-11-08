package okr

import (
	"database/sql"
	"encoding/json"
	"errors"
	"os"
	"strings"
)

type ProjectOperationReceipt struct {
	Key            string `json:"key"`
	Kind           string `json:"kind"`
	RequestSHA256  string `json:"requestSha256"`
	ReviewID       string `json:"reviewId,omitempty"`
	ObservationID  string `json:"observationId,omitempty"`
	PreviousSHA256 string `json:"previousSha256,omitempty"`
	ResultSHA256   string `json:"resultSha256,omitempty"`
	RecordedAt     string `json:"recordedAt"`
}

type memoryAppendIntent struct {
	Content        string `json:"content"`
	PreviousSHA256 string `json:"previousSha256"`
	ResultSHA256   string `json:"resultSha256"`
}

type memoryEditIntent struct {
	Result         string `json:"result"`
	PreviousSHA256 string `json:"previousSha256"`
	ResultSHA256   string `json:"resultSha256"`
}

type projectOperationIntent struct {
	Revision    int64               `json:"revision"`
	Review      *Review             `json:"review,omitempty"`
	Observation *Observation        `json:"observation,omitempty"`
	Memory      *memoryAppendIntent `json:"memory,omitempty"`
	MemoryEdit  *memoryEditIntent   `json:"memoryEdit,omitempty"`
}

type projectOperation struct {
	Key           string
	Kind          string
	RequestSHA256 string
	Intent        projectOperationIntent
	Receipt       *ProjectOperationReceipt
}

func operationDigest(key, kind string, request any) (string, error) {
	if key == "" || len(key) > 200 || strings.ContainsAny(key, "\x00\r\n") {
		return "", ErrInvalid
	}
	body, err := json.Marshal(request)
	if err != nil {
		return "", err
	}
	return hashText(append([]byte(kind+"\x00"), body...)), nil
}

func (s *Store) operationRoot(projectID string) (*os.Root, func(), error) {
	if s.projects == nil {
		return nil, nil, ErrInvalid
	}
	w, err := s.Get(projectID)
	if err != nil {
		return nil, nil, err
	}
	if w == nil || w.ProjectFiles == nil {
		return nil, nil, ErrNotFound
	}
	root, err := s.openBundle(projectID, false)
	if err != nil {
		return nil, nil, err
	}
	unlock, err := lockBundle(root)
	if err != nil {
		root.Close()
		return nil, nil, err
	}
	return root, func() { unlock(); root.Close() }, nil
}

func (s *Store) readOperation(projectID, key, kind, digest string) (*projectOperation, error) {
	var storedKind, storedDigest, intent, state string
	var receipt sql.NullString
	err := s.db.QueryRow(`SELECT kind,request_sha256,intent_json,state,receipt_json FROM project_operations WHERE project_id=? AND operation_key=?`, projectID, key).Scan(&storedKind, &storedDigest, &intent, &state, &receipt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if storedKind != kind || storedDigest != digest {
		return nil, ErrConflict
	}
	op := &projectOperation{Key: key, Kind: kind, RequestSHA256: digest}
	if json.Unmarshal([]byte(intent), &op.Intent) != nil {
		return nil, ErrInvalid
	}
	if state == "applied" {
		op.Receipt = &ProjectOperationReceipt{}
		if !receipt.Valid || json.Unmarshal([]byte(receipt.String), op.Receipt) != nil || op.Receipt.Key != key || op.Receipt.Kind != kind || op.Receipt.RequestSHA256 != digest {
			return nil, ErrInvalid
		}
	}
	return op, nil
}

func (s *Store) prepareOperation(projectID string, op *projectOperation) error {
	body, err := json.Marshal(op.Intent)
	if err != nil {
		return err
	}
	_, err = s.db.Exec(`INSERT INTO project_operations(project_id,operation_key,kind,request_sha256,intent_json,state,created_at) VALUES(?,?,?,?,?,'prepared',?)`, projectID, op.Key, op.Kind, op.RequestSHA256, string(body), timestamp(s.now()))
	return err
}

func (s *Store) finishOperation(projectID string, op *projectOperation) (*Workspace, error) {
	receipt := ProjectOperationReceipt{Key: op.Key, Kind: op.Kind, RequestSHA256: op.RequestSHA256, RecordedAt: timestamp(s.now())}
	if op.Intent.Review != nil {
		receipt.ReviewID = op.Intent.Review.ID
	}
	if op.Intent.Observation != nil {
		receipt.ObservationID = op.Intent.Observation.ID
	}
	if op.Intent.Memory != nil {
		receipt.PreviousSHA256 = op.Intent.Memory.PreviousSHA256
		receipt.ResultSHA256 = op.Intent.Memory.ResultSHA256
	}
	if op.Intent.MemoryEdit != nil {
		receipt.PreviousSHA256 = op.Intent.MemoryEdit.PreviousSHA256
		receipt.ResultSHA256 = op.Intent.MemoryEdit.ResultSHA256
	}
	body, err := json.Marshal(receipt)
	if err != nil {
		return nil, err
	}
	result, err := s.db.Exec(`UPDATE project_operations SET state='applied',receipt_json=? WHERE project_id=? AND operation_key=? AND request_sha256=? AND state='prepared'`, string(body), projectID, op.Key, op.RequestSHA256)
	if err != nil {
		return nil, err
	}
	count, err := result.RowsAffected()
	if err != nil || count != 1 {
		if err != nil {
			return nil, err
		}
		return nil, ErrConflict
	}
	return s.operationWorkspace(projectID, &receipt)
}

func (s *Store) operationWorkspace(projectID string, receipt *ProjectOperationReceipt) (*Workspace, error) {
	w, err := s.Get(projectID)
	if err != nil {
		return nil, err
	}
	if w == nil || w.ProjectFiles == nil {
		return nil, ErrNotFound
	}
	w.ProjectFiles.OperationReceipt = receipt
	return w, nil
}
