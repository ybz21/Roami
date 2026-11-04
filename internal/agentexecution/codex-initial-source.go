package agentexecution

import (
	"bufio"
	"bytes"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"syscall"
	"time"
)

type codexInitialSource struct {
	ID         string          `json:"id"`
	Cwd        string          `json:"cwd"`
	Originator string          `json:"originator"`
	Source     json.RawMessage `json:"source"`
}

type codexInitialCompletion struct {
	ProviderID string
	TurnID     string
	CreatedMS  int64
	Proof      string
	Result     *Result
}

func initialCodexCompletion(binding SessionBinding, promptHash string) *codexInitialCompletion {
	created, err := strconv.ParseInt(binding.Created, 10, 64)
	if err != nil {
		return nil
	}
	home := os.Getenv("CODEX_HOME")
	if home == "" {
		userHome, err := os.UserHomeDir()
		if err != nil {
			return nil
		}
		home = filepath.Join(userHome, ".codex")
	}
	root, err := filepath.EvalSymlinks(filepath.Join(home, "sessions"))
	if err != nil {
		return nil
	}
	paths, err := filepath.Glob(filepath.Join(root, "*", "*", "*", "rollout-*.jsonl"))
	if err != nil || len(paths) > 10000 {
		return nil
	}
	var candidate *codexInitialCompletion
	for _, path := range paths {
		info, err := os.Lstat(path)
		if err != nil {
			return nil
		}
		if info.ModTime().Unix() < created-1 {
			continue
		}
		resolved, err := filepath.EvalSymlinks(path)
		owner, ok := info.Sys().(*syscall.Stat_t)
		if err != nil || resolved != path || !ok || owner.Uid != uint32(os.Geteuid()) || !info.Mode().IsRegular() || info.Mode().Perm()&0002 != 0 {
			return nil
		}
		file, err := os.Open(path)
		if err != nil {
			return nil
		}
		first, readErr := bufio.NewReader(io.LimitReader(file, 64<<10)).ReadBytes('\n')
		var record codexRecord
		var source codexInitialSource
		if readErr != nil || json.Unmarshal(first, &record) != nil || record.Type != "session_meta" || json.Unmarshal(record.Payload, &source) != nil {
			file.Close()
			return nil
		}
		var kind string
		if json.Unmarshal(source.Source, &kind) != nil || kind != "cli" {
			file.Close()
			continue
		}
		directory, err := canonicalWorkspace(source.Cwd)
		if err != nil {
			file.Close()
			return nil
		}
		if directory != binding.Directory {
			file.Close()
			continue
		}
		if info.Size() > 64<<20 {
			file.Close()
			return nil
		}
		// Any other recent CLI root in this directory makes initial recovery ambiguous.
		if candidate != nil || source.Originator != "codex-tui" || !codexThreadID.MatchString(source.ID) {
			file.Close()
			return nil
		}
		stamp, err := time.Parse(time.RFC3339Nano, record.Timestamp)
		if err != nil || stamp.Unix() < created-1 {
			file.Close()
			return nil
		}
		tail := make([]byte, min(info.Size(), 256<<10))
		_, readErr = file.ReadAt(tail, info.Size()-int64(len(tail)))
		opened, statErr := file.Stat()
		file.Close()
		tail = bytes.TrimSpace(tail)
		var terminal codexRecord
		var end codexPayload
		if readErr != nil || statErr != nil || !os.SameFile(info, opened) || opened.Size() != info.Size() || !opened.ModTime().Equal(info.ModTime()) || json.Unmarshal(tail[bytes.LastIndexByte(tail, '\n')+1:], &terminal) != nil || terminal.Type != "event_msg" || json.Unmarshal(terminal.Payload, &end) != nil || end.Type != "task_complete" || end.TurnID == "" || end.RootTurnID != end.TurnID {
			return nil
		}
		current := binding
		current.ProviderID = source.ID
		result, proof := codexTranscriptOutcome(current, end.TurnID, promptHash, false, true)
		if result == nil || result.FinishedMS < created*1000 || result.FinishedMS > time.Now().Add(time.Second).UnixMilli() {
			return nil
		}
		candidate = &codexInitialCompletion{source.ID, end.TurnID, stamp.UnixMilli(), proof, result}
	}
	return candidate
}
