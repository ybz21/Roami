package okr

import (
	"bytes"
	"errors"
	"io/fs"
	"os"
)

func appendedMemory(previous []byte, content string) []byte {
	if len(previous) == 0 {
		return []byte(content)
	}
	if content == "" {
		return bytes.Clone(previous)
	}
	separator := "\n\n"
	if bytes.HasSuffix(previous, []byte("\n\n")) {
		separator = ""
	} else if bytes.HasSuffix(previous, []byte("\n")) {
		separator = "\n"
	}
	return []byte(string(previous) + separator + content)
}

func memoryVersionApplied(root *os.Root, current []byte, resultSHA256 string) (bool, error) {
	if hashText(current) == resultSHA256 {
		return true, nil
	}
	historical, err := readFile(root, "memory/history/"+resultSHA256+".md", maxMemory)
	if errors.Is(err, fs.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if hashText(historical) != resultSHA256 {
		return false, ErrInvalid
	}
	return true, nil
}

func (s *Store) AppendMemoryOnce(projectID, key, content, expectedSHA256 string) (*Workspace, error) {
	if len(content) > maxMemory || !validDigest(expectedSHA256) {
		return nil, ErrInvalid
	}
	digest, err := operationDigest(key, "memory_append", struct{ Content string }{content})
	if err != nil {
		return nil, err
	}
	root, close, err := s.operationRoot(projectID)
	if err != nil {
		return nil, err
	}
	defer close()
	op, err := s.readOperation(projectID, key, "memory_append", digest)
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
		result := appendedMemory(current, content)
		if len(result) > maxMemory {
			return nil, ErrInvalid
		}
		op = &projectOperation{Key: key, Kind: "memory_append", RequestSHA256: digest, Intent: projectOperationIntent{Memory: &memoryAppendIntent{Content: content, PreviousSHA256: expectedSHA256, ResultSHA256: hashText(result)}}}
		if err := s.prepareOperation(projectID, op); err != nil {
			return nil, err
		}
	}
	intent := op.Intent.Memory
	if intent == nil {
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
	result := appendedMemory(current, intent.Content)
	if len(result) > maxMemory || hashText(result) != intent.ResultSHA256 {
		return nil, ErrConflict
	}
	if !bytes.Equal(current, result) {
		if err := atomicFile(root, "memory/history/"+intent.PreviousSHA256+".md", current); err != nil {
			return nil, err
		}
		if err := atomicFile(root, "memory/team.md", result); err != nil {
			return nil, err
		}
	}
	return s.finishOperation(projectID, op)
}
