package agentexecution

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

func untrackedCodexLaunch(state *sessionLifecycle, spec Spec, key string) bool {
	conflict := state.ProviderConflict
	foreign := conflict != nil && (conflict.Executor != "codex" || conflict.Hook != "" || conflict.Type != "agent-turn-complete")
	return state.Executor == "codex" && state.State == "unknown" && state.UnknownReason == "SESSION_START_UNTRACKED" && !state.InitialLaunch && len(state.Tools) == 0 && !foreign && state.LaunchKey == key && spec.Key == key && spec.Executor == "codex" && spec.SessionID == state.Binding.ID
}

func codexUntrackedLaunchStop(binding SessionBinding, dir string, spec Spec) (*Result, string, map[string]int64) {
	info, err := os.Stat(filepath.Join(dir, "spec.json"))
	if err != nil {
		return nil, "", nil
	}
	return codexUntrackedStop(binding, workspaceHash(sessionPrompt(dir, spec)), info.ModTime().UnixMilli())
}

// A missing start hook can only be reconciled as stopped, never as task success.
func codexUntrackedStop(binding SessionBinding, promptHash string, sinceMS int64) (*Result, string, map[string]int64) {
	if !codexThreadID.MatchString(binding.ProviderID) || promptHash == "" || sinceMS <= 0 {
		return nil, "", nil
	}
	home := binding.ProviderHome
	if home == "" {
		home = os.Getenv("CODEX_HOME")
	}
	if home == "" {
		base, err := os.UserHomeDir()
		if err != nil {
			return nil, "", nil
		}
		home = filepath.Join(base, ".codex")
	}
	root, err := filepath.EvalSymlinks(filepath.Join(home, "sessions"))
	if err != nil {
		return nil, "", nil
	}
	paths, err := filepath.Glob(filepath.Join(root, "*", "*", "*", "rollout-*-"+binding.ProviderID+".jsonl"))
	if err != nil || len(paths) != 1 {
		return nil, "", nil
	}
	path := paths[0]
	canonical, err := filepath.EvalSymlinks(path)
	if err != nil || canonical != path {
		return nil, "", nil
	}
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0002 != 0 || info.Size() > 256<<20 {
		return nil, "", nil
	}
	owner, ok := info.Sys().(*syscall.Stat_t)
	if !ok || owner.Uid != uint32(os.Geteuid()) {
		return nil, "", nil
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, "", nil
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !os.SameFile(info, opened) {
		return nil, "", nil
	}
	tail := make([]byte, min(info.Size(), 256<<10))
	if _, err = file.ReadAt(tail, info.Size()-int64(len(tail))); err != nil {
		return nil, "", nil
	}
	line := strings.TrimSpace(string(tail))
	if at := strings.LastIndexByte(line, '\n'); at >= 0 {
		line = line[at+1:]
	}
	var last codexRecord
	var end codexPayload
	if json.Unmarshal([]byte(line), &last) != nil || last.Type != "event_msg" || json.Unmarshal(last.Payload, &end) != nil || end.Type != "task_complete" || end.TurnID == "" || end.RootTurnID != end.TurnID {
		return nil, "", nil
	}
	if _, err = file.Seek(0, io.SeekStart); err != nil {
		return nil, "", nil
	}
	digest := sha256.New()
	decoder := json.NewDecoder(io.TeeReader(io.LimitReader(file, (256<<20)+1), digest))
	metadata, authenticated, terminal, final := false, false, false, false
	active, answer := "", ""
	matched := 0
	calls := map[string]bool{}
	started := int64(0)
	for {
		var record codexRecord
		if err = decoder.Decode(&record); err == io.EOF {
			break
		} else if err != nil {
			return nil, "", nil
		}
		var value codexPayload
		if json.Unmarshal(record.Payload, &value) != nil {
			return nil, "", nil
		}
		if record.Type == "session_meta" {
			dir, e := canonicalWorkspace(value.Cwd)
			if e != nil || dir != binding.Directory || value.ID != binding.ProviderID {
				return nil, "", nil
			}
			metadata = true
			continue
		}
		if record.Type == "event_msg" && value.Type == "task_started" {
			stamp, e := time.Parse(time.RFC3339Nano, record.Timestamp)
			if e != nil {
				return nil, "", nil
			}
			if authenticated && (!terminal || len(calls) != 0) {
				return nil, "", nil
			}
			active, started, terminal, final, answer = value.TurnID, stamp.UnixMilli(), false, false, ""
			if value.RootTurnID != "" && value.RootTurnID != active {
				return nil, "", nil
			}
			calls = map[string]bool{}
			continue
		}
		if active == "" || started < sinceMS {
			continue
		}
		if record.Type == "response_item" {
			switch value.Type {
			case "message":
				text := ""
				for _, part := range value.Content {
					if part.Type == "input_text" || part.Type == "output_text" || part.Type == "text" {
						text += part.Text
					}
				}
				if value.Role == "user" {
					if workspaceHash(text) == promptHash {
						matched++
						authenticated = true
					}
					terminal, final = false, false
				} else if value.Role == "assistant" {
					answer, final = text, value.Phase == "final_answer"
				}
			case "function_call", "custom_tool_call":
				if value.CallID == "" || calls[value.CallID] {
					return nil, "", nil
				}
				calls[value.CallID] = true
			case "function_call_output", "custom_tool_call_output":
				if !calls[value.CallID] {
					return nil, "", nil
				}
				delete(calls, value.CallID)
			default:
				if strings.HasSuffix(value.Type, "_call") && value.Status != "completed" {
					return nil, "", nil
				}
			}
		}
		if authenticated && record.Type == "event_msg" {
			if value.Type == "turn_aborted" || value.Type == "task_failed" {
				return nil, "", nil
			}
			if value.Type == "task_complete" {
				if value.TurnID != active || value.RootTurnID != active || !final || answer == "" || answer != value.LastAssistant || len(calls) != 0 {
					return nil, "", nil
				}
				terminal = true
			}
		}
	}
	after, err := file.Stat()
	if err != nil || !metadata || matched != 1 || !terminal || active != end.TurnID || after.Size() != info.Size() || !after.ModTime().Equal(info.ModTime()) {
		return nil, "", nil
	}
	current, err := os.Lstat(path)
	if err != nil || !os.SameFile(info, current) || current.Mode().Perm()&0002 != 0 {
		return nil, "", nil
	}
	finished, err := time.Parse(time.RFC3339Nano, last.Timestamp)
	if err != nil || finished.UnixMilli() < started || finished.UnixMilli() < sinceMS {
		return nil, "", nil
	}
	return &Result{State: "failed", Summary: "SESSION_SCOPE_CHANGED_STOPPED", FinishedMS: finished.UnixMilli()}, hex.EncodeToString(digest.Sum(nil)), map[string]int64{}
}
