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

func TestMemoryEditKeepsHistoryAndDoesNotRepeatAfterNewKnowledge(t *testing.T) {
	s, project := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	original := "# Team\r\nCurrent: old rule\r\nUnrelated verified fact.\n"
	w, err = s.WriteMemory("project", original, w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	before := w.ProjectFiles.TeamMemorySha256
	edits := []MemoryEdit{{"old rule", "new rule"}, {"# Team", "# Current team"}}
	w, err = s.EditMemoryOnce("project", "rule-edit-1", before, edits)
	if err != nil {
		t.Fatal(err)
	}
	want := "# Current team\r\nCurrent: new rule\r\nUnrelated verified fact.\n"
	if w.ProjectFiles.TeamMemory != want || w.ProjectFiles.OperationReceipt.Kind != "memory_edit" || w.ProjectFiles.OperationReceipt.PreviousSHA256 != before || w.ProjectFiles.OperationReceipt.ResultSHA256 != hashText([]byte(want)) {
		t.Fatal("edit lost bytes or its real receipt", w.ProjectFiles)
	}
	receipt := *w.ProjectFiles.OperationReceipt
	prior, err := os.ReadFile(filepath.Join(project, bundleRoot, "memory/history", before+".md"))
	if err != nil || string(prior) != original {
		t.Fatal("original memory not retained", err)
	}
	w, err = s.AppendMemory("project", "Later verified fact.", w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	newer := w.ProjectFiles.TeamMemory
	w, err = s.EditMemoryOnce("project", "rule-edit-1", w.ProjectFiles.TeamMemorySha256, edits)
	if err != nil || w.ProjectFiles.TeamMemory != newer || !reflect.DeepEqual(*w.ProjectFiles.OperationReceipt, receipt) {
		t.Fatal("replay changed later knowledge or the original receipt", err)
	}
	if _, err := s.EditMemoryOnce("project", "rule-edit-1", before, []MemoryEdit{{"old rule", "different"}}); !errors.Is(err, ErrConflict) {
		t.Fatal("same operation key accepted a different edit", err)
	}
}

func TestMemoryEditRejectsTheWholeBatchBeforeAnyWrite(t *testing.T) {
	for name, edits := range map[string][]MemoryEdit{
		"missing":   {{"current", "changed"}, {"missing", "new"}},
		"ambiguous": {{"aa", "new"}},
		"overlap":   {{"current", "changed"}, {"urrent", "new"}},
		"empty":     {{"", "new"}},
		"no-change": {{"current", "current"}},
		"oversized": {{"current", strings.Repeat("x", maxMemory)}},
		"invalid":   {{"current", string([]byte{0xff})}},
	} {
		t.Run(name, func(t *testing.T) {
			s, project := fileStore(t)
			w, err := s.Save("project", testConfig())
			if err != nil {
				t.Fatal(err)
			}
			original := "current\naaa\nuntouched"
			w, err = s.WriteMemory("project", original, w.ProjectFiles.TeamMemorySha256)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := s.EditMemoryOnce("project", "invalid-batch", w.ProjectFiles.TeamMemorySha256, edits); err == nil {
				t.Fatal("invalid batch succeeded")
			}
			body, err := os.ReadFile(filepath.Join(project, bundleRoot, "memory/team.md"))
			if err != nil || string(body) != original {
				t.Fatal("failed batch changed current memory", err)
			}
			var count int
			if err := s.db.QueryRow("SELECT count(*) FROM project_operations WHERE operation_key='invalid-batch'").Scan(&count); err != nil || count != 0 {
				t.Fatal("invalid batch prepared an operation", count, err)
			}
		})
	}
}

func TestMemoryEditConcurrentCASAcceptsOnlyOneWriter(t *testing.T) {
	s, _ := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	w, err = s.WriteMemory("project", "current rule", w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	sha := w.ProjectFiles.TeamMemorySha256
	errorsFound := make(chan error, 2)
	var writers sync.WaitGroup
	for _, key := range []string{"edit-a", "edit-b"} {
		writers.Add(1)
		go func(key string) {
			defer writers.Done()
			_, err := s.EditMemoryOnce("project", key, sha, []MemoryEdit{{"current rule", key}})
			errorsFound <- err
		}(key)
	}
	writers.Wait()
	close(errorsFound)
	passed, conflicts := 0, 0
	for err := range errorsFound {
		if err == nil {
			passed++
		} else if errors.Is(err, ErrConflict) {
			conflicts++
		} else {
			t.Fatal(err)
		}
	}
	if passed != 1 || conflicts != 1 {
		t.Fatal(passed, conflicts)
	}
}

func TestMemoryEditPreparedRecoveryDoesNotRollBackLaterAppend(t *testing.T) {
	s, project := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	w, err = s.WriteMemory("project", "old rule", w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	edits := []MemoryEdit{{"old rule", "new rule"}}
	digest, _ := operationDigest("recover-edit", "memory_edit", struct{ Edits []MemoryEdit }{edits})
	intent := &memoryEditIntent{Result: "new rule", PreviousSHA256: w.ProjectFiles.TeamMemorySha256, ResultSHA256: hashText([]byte("new rule"))}
	op := &projectOperation{Key: "recover-edit", Kind: "memory_edit", RequestSHA256: digest, Intent: projectOperationIntent{MemoryEdit: intent}}
	if err := s.prepareOperation("project", op); err != nil {
		t.Fatal(err)
	}
	root, err := os.OpenRoot(filepath.Join(project, bundleRoot))
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	if err := atomicFile(root, "memory/history/"+intent.PreviousSHA256+".md", []byte("old rule")); err != nil {
		t.Fatal(err)
	}
	if err := atomicFile(root, "memory/team.md", []byte(intent.Result)); err != nil {
		t.Fatal(err)
	}
	w, err = s.AppendMemory("project", "Later fact", intent.ResultSHA256)
	if err != nil {
		t.Fatal(err)
	}
	current := w.ProjectFiles.TeamMemory
	w, err = s.EditMemoryOnce("project", "recover-edit", intent.PreviousSHA256, edits)
	if err != nil || w.ProjectFiles.TeamMemory != current || w.ProjectFiles.OperationReceipt.ResultSHA256 != intent.ResultSHA256 {
		t.Fatal("recovery lost subsequent knowledge", err)
	}
}
