package okr

import (
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
)

func TestReviewOperationKeepsOneOriginalReceiptAfterNewRevision(t *testing.T) {
	s, _ := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	w, err = s.ReviewOnce("project", "cycle:review", w.Revision, "Verified result", "Next bounded experiment")
	if err != nil {
		t.Fatal(err)
	}
	receipt := w.ProjectFiles.OperationReceipt
	review := w.Reviews[0]
	w, err = s.Observe("project", w.Revision, "users", "2026-11-02", 0, "Valid measured zero")
	if err != nil {
		t.Fatal(err)
	}
	currentRevision := w.Revision
	w, err = s.ReviewOnce("project", "cycle:review", currentRevision, "Verified result", "Next bounded experiment")
	if err != nil {
		t.Fatal(err)
	}
	if w.Revision != currentRevision || len(w.Reviews) != 1 || w.Reviews[0] != review || !reflect.DeepEqual(receipt, w.ProjectFiles.OperationReceipt) {
		t.Fatal(w.Reviews, w.ProjectFiles.OperationReceipt)
	}
	evidence, err := s.Evidence("project", review.ID)
	if err != nil || evidence.Revision != review.EvidenceRevision || len(evidence.Observations) != 0 || len(evidence.Reviews) != 0 {
		t.Fatal("replay changed the original review's evidence", evidence, err)
	}
	if _, err = s.ReviewOnce("project", "cycle:review", w.Revision, "Changed result", "Next bounded experiment"); !errors.Is(err, ErrConflict) {
		t.Fatal(err)
	}
}

func TestObservationOperationRetainsZeroAndRejectsChangedPayload(t *testing.T) {
	s, _ := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	w, err = s.ObserveOnce("project", "cycle:users", w.Revision, "users", "2026-11-02", 0, "Source confirms zero")
	if err != nil {
		t.Fatal(err)
	}
	receipt := w.ProjectFiles.OperationReceipt
	w, err = s.ObserveOnce("project", "cycle:users", w.Revision, "users", "2026-11-02", 0, "Source confirms zero")
	if err != nil {
		t.Fatal(err)
	}
	if len(w.Observations) != 1 || w.Observations[0].Value != 0 || !reflect.DeepEqual(receipt, w.ProjectFiles.OperationReceipt) {
		t.Fatal(w)
	}
	if _, err = s.ObserveOnce("project", "cycle:users", w.Revision, "users", "2026-11-02", 1, "Source confirms zero"); !errors.Is(err, ErrConflict) {
		t.Fatal(err)
	}
}

func TestMemoryOperationDoesNotAppendAgainAfterFreshCAS(t *testing.T) {
	s, _ := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	original := "# Team\nPrior exact bytes.\n\n\n"
	w, err = s.WriteMemory("project", original, w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	w, err = s.AppendMemoryOnce("project", "cycle:memory", "Verified round note", w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	receipt := w.ProjectFiles.OperationReceipt
	w, err = s.AppendMemory("project", "Later independent note", w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	current := w.ProjectFiles.TeamMemory
	w, err = s.AppendMemoryOnce("project", "cycle:memory", "Verified round note", w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	if w.ProjectFiles.TeamMemory != current || !strings.HasPrefix(current, original) || strings.Count(current, "Verified round note") != 1 || !reflect.DeepEqual(receipt, w.ProjectFiles.OperationReceipt) {
		t.Fatal(w.ProjectFiles)
	}
	if _, err = s.AppendMemoryOnce("project", "cycle:memory", "Different note", w.ProjectFiles.TeamMemorySha256); !errors.Is(err, ErrConflict) {
		t.Fatal(err)
	}
}

func TestAppliedFileEffectReconcilesAfterReceiptFailureAndStoreRestart(t *testing.T) {
	for _, kind := range []string{"review", "observation", "memory_append"} {
		t.Run(kind, func(t *testing.T) {
			s, paths := testStore(t)
			directory := t.TempDir()
			projects := func() map[string]string { return map[string]string{"project": directory} }
			s.SetProjects(projects)
			w, err := s.Save("project", testConfig())
			if err != nil {
				t.Fatal(err)
			}
			call := func(s *Store, w *Workspace) (*Workspace, error) {
				switch kind {
				case "review":
					return s.ReviewOnce("project", "same-business", w.Revision, "Review once", "Follow up")
				case "observation":
					return s.ObserveOnce("project", "same-business", w.Revision, "users", "2026-11-02", 3, "Confirmed")
				default:
					return s.AppendMemoryOnce("project", "same-business", "Memory once", w.ProjectFiles.TeamMemorySha256)
				}
			}
			if _, err = s.db.Exec(`CREATE TRIGGER reject_receipt BEFORE UPDATE OF state ON project_operations BEGIN SELECT RAISE(ABORT,'receipt unavailable'); END;`); err != nil {
				t.Fatal(err)
			}
			if _, err = call(s, w); err == nil {
				t.Fatal("receipt failure was hidden")
			}
			actual, err := s.Get("project")
			if err != nil {
				t.Fatal(err)
			}
			var state string
			if err = s.db.QueryRow(`SELECT state FROM project_operations WHERE operation_key='same-business'`).Scan(&state); err != nil || state != "prepared" {
				t.Fatal(state, err)
			}
			if _, err = s.db.Exec(`DROP TRIGGER reject_receipt`); err != nil {
				t.Fatal(err)
			}
			if err = s.db.Close(); err != nil {
				t.Fatal(err)
			}
			reopened, err := Open(paths)
			if err != nil {
				t.Fatal(err)
			}
			defer reopened.db.Close()
			reopened.SetProjects(projects)
			recovered, err := call(reopened, actual)
			if err != nil {
				t.Fatal(err)
			}
			if recovered.Revision != actual.Revision || !reflect.DeepEqual(recovered.Reviews, actual.Reviews) || !reflect.DeepEqual(recovered.Observations, actual.Observations) || recovered.ProjectFiles.TeamMemory != actual.ProjectFiles.TeamMemory {
				t.Fatal("recovery repeated a committed effect")
			}
			if recovered.ProjectFiles.OperationReceipt == nil {
				t.Fatal("missing original operation receipt")
			}
		})
	}
}

func TestMemoryPreparedEffectUsesHistoryAfterLaterAppend(t *testing.T) {
	s, _ := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.db.Exec(`CREATE TRIGGER reject_receipt BEFORE UPDATE OF state ON project_operations BEGIN SELECT RAISE(ABORT,'receipt unavailable'); END;`); err != nil {
		t.Fatal(err)
	}
	if _, err = s.AppendMemoryOnce("project", "memory:one", "First note", w.ProjectFiles.TeamMemorySha256); err == nil {
		t.Fatal("expected receipt failure")
	}
	w, err = s.Get("project")
	if err != nil {
		t.Fatal(err)
	}
	w, err = s.AppendMemory("project", "Later note", w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	before := w.ProjectFiles.TeamMemory
	if _, err = s.db.Exec(`DROP TRIGGER reject_receipt`); err != nil {
		t.Fatal(err)
	}
	w, err = s.AppendMemoryOnce("project", "memory:one", "First note", w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	if w.ProjectFiles.TeamMemory != before || strings.Count(before, "First note") != 1 {
		t.Fatal(w.ProjectFiles.TeamMemory)
	}
}

func TestPreparedReviewCannotUseANewRevisionToRepeatOrOverwrite(t *testing.T) {
	s, directory := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	projection := filepath.Join(directory, bundleRoot, "data/reviews.jsonl")
	if err = os.Remove(projection); err != nil {
		t.Fatal(err)
	}
	if err = os.Mkdir(projection, 0700); err != nil {
		t.Fatal(err)
	}
	if _, err = s.ReviewOnce("project", "review:pending", w.Revision, "Not yet committed", "Follow up"); err == nil {
		t.Fatal("unsafe projection should fail")
	}
	if err = os.Remove(projection); err != nil {
		t.Fatal(err)
	}
	current, err := s.Get("project")
	if err != nil {
		t.Fatal(err)
	}
	if len(current.Reviews) != 0 || current.Revision != w.Revision {
		t.Fatal("unconfirmed projection counted as success")
	}
	current, err = s.Observe("project", current.Revision, "users", "2026-11-02", 4, "New independent evidence")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.ReviewOnce("project", "review:pending", current.Revision, "Not yet committed", "Follow up"); !errors.Is(err, ErrConflict) {
		t.Fatal(err)
	}
}

func TestConcurrentSameMemoryOperationReturnsOneReceipt(t *testing.T) {
	s, _ := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	results := make(chan *Workspace, 2)
	failures := make(chan error, 2)
	var group sync.WaitGroup
	for range 2 {
		group.Add(1)
		go func() {
			defer group.Done()
			value, err := s.AppendMemoryOnce("project", "shared:memory", "One appended note", w.ProjectFiles.TeamMemorySha256)
			results <- value
			failures <- err
		}()
	}
	group.Wait()
	close(results)
	close(failures)
	for err := range failures {
		if err != nil {
			t.Fatal(err)
		}
	}
	var receipt *ProjectOperationReceipt
	for value := range results {
		if strings.Count(value.ProjectFiles.TeamMemory, "One appended note") != 1 {
			t.Fatal(value.ProjectFiles.TeamMemory)
		}
		if receipt != nil && !reflect.DeepEqual(receipt, value.ProjectFiles.OperationReceipt) {
			t.Fatal("receipts diverged")
		}
		receipt = value.ProjectFiles.OperationReceipt
	}
}
