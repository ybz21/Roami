package okr

import (
	"sort"
	"strings"
	"unicode/utf8"
)

type MemoryEdit struct {
	OldText string `json:"oldText"`
	NewText string `json:"newText"`
}

func validMemoryEdits(edits []MemoryEdit) bool {
	if len(edits) == 0 || len(edits) > 16 {
		return false
	}
	size := 0
	for _, edit := range edits {
		size += len(edit.OldText) + len(edit.NewText)
		if edit.OldText == "" || edit.OldText == edit.NewText || size > maxMemory || !utf8.ValidString(edit.OldText) || !utf8.ValidString(edit.NewText) {
			return false
		}
	}
	return true
}

func editedMemory(current []byte, edits []MemoryEdit) ([]byte, error) {
	if !validMemoryEdits(edits) || !utf8.Valid(current) {
		return nil, ErrInvalid
	}
	type replacement struct {
		start, end int
		text       string
	}
	resultSize := len(current)
	original := string(current)
	changes := make([]replacement, 0, len(edits))
	for _, edit := range edits {
		start := strings.Index(original, edit.OldText)
		if start < 0 || start != strings.LastIndex(original, edit.OldText) {
			return nil, ErrConflict
		}
		changes = append(changes, replacement{start, start + len(edit.OldText), edit.NewText})
		resultSize += len(edit.NewText) - len(edit.OldText)
	}
	if resultSize > maxMemory {
		return nil, ErrInvalid
	}
	sort.Slice(changes, func(i, j int) bool { return changes[i].start < changes[j].start })
	for i := 1; i < len(changes); i++ {
		if changes[i].start < changes[i-1].end {
			return nil, ErrConflict
		}
	}
	result := original
	for i := len(changes) - 1; i >= 0; i-- {
		change := changes[i]
		result = result[:change.start] + change.text + result[change.end:]
	}
	return []byte(result), nil
}

func (s *Store) EditMemoryOnce(projectID, key, expectedSHA256 string, edits []MemoryEdit) (*Workspace, error) {
	if !validDigest(expectedSHA256) || !validMemoryEdits(edits) {
		return nil, ErrInvalid
	}
	digest, err := operationDigest(key, "memory_edit", struct{ Edits []MemoryEdit }{edits})
	if err != nil {
		return nil, err
	}
	root, close, err := s.operationRoot(projectID)
	if err != nil {
		return nil, err
	}
	defer close()
	op, err := s.readOperation(projectID, key, "memory_edit", digest)
	if err != nil {
		return nil, err
	}
	if op != nil && op.Receipt != nil {
		return s.operationWorkspace(projectID, op.Receipt)
	}
	current, err := readFile(root, "memory/team.md", maxMemory)
	if err != nil {
		return nil, err
	}
	if op == nil {
		if hashText(current) != expectedSHA256 {
			return nil, ErrConflict
		}
		result, err := editedMemory(current, edits)
		if err != nil {
			return nil, err
		}
		op = &projectOperation{Key: key, Kind: "memory_edit", RequestSHA256: digest, Intent: projectOperationIntent{MemoryEdit: &memoryEditIntent{Result: string(result), PreviousSHA256: expectedSHA256, ResultSHA256: hashText(result)}}}
		if err := s.prepareOperation(projectID, op); err != nil {
			return nil, err
		}
	}
	intent := op.Intent.MemoryEdit
	if intent == nil || !validDigest(intent.PreviousSHA256) || !validDigest(intent.ResultSHA256) || len(intent.Result) > maxMemory || !utf8.ValidString(intent.Result) || hashText([]byte(intent.Result)) != intent.ResultSHA256 {
		return nil, ErrInvalid
	}
	applied, err := memoryVersionApplied(root, current, intent.ResultSHA256)
	if err != nil {
		return nil, err
	}
	if applied {
		return s.finishOperation(projectID, op)
	}
	if hashText(current) != intent.PreviousSHA256 {
		return nil, ErrConflict
	}
	if err := atomicFile(root, "memory/history/"+intent.PreviousSHA256+".md", current); err != nil {
		return nil, err
	}
	if err := atomicFile(root, "memory/team.md", []byte(intent.Result)); err != nil {
		return nil, err
	}
	return s.finishOperation(projectID, op)
}
