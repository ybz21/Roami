package agentexecution

import (
	"encoding/binary"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

func initialProcessStartedMS(token string) (int64, error) {
	aux, err := os.ReadFile("/proc/self/auxv")
	if err != nil {
		return 0, err
	}
	word := strconv.IntSize / 8
	read := func(data []byte) uint64 {
		if word == 8 {
			return binary.NativeEndian.Uint64(data)
		}
		return uint64(binary.NativeEndian.Uint32(data))
	}
	var ticks uint64
	for at := 0; at+2*word <= len(aux); at += 2 * word {
		if read(aux[at:]) == 17 {
			ticks = read(aux[at+word:])
			break
		} // ELF AT_CLKTCK.
	}
	stat, err := os.ReadFile("/proc/stat")
	if err != nil || ticks == 0 {
		return 0, fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
	}
	var boot uint64
	for _, line := range strings.Split(string(stat), "\n") {
		if strings.HasPrefix(line, "btime ") {
			boot, err = strconv.ParseUint(strings.TrimSpace(strings.TrimPrefix(line, "btime ")), 10, 64)
			break
		}
	}
	start, parseErr := strconv.ParseUint(token, 10, 64)
	if err != nil || parseErr != nil || boot == 0 {
		return 0, fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
	}
	return int64(boot*1000 + start*1000/ticks), nil
}

func initialCodexProcesses(binding SessionBinding, prompt string, sourceMS int64, launchHash string) (SessionBinding, bool) {
	snapshot, scope, scoped, err := paneProcessSnapshot(binding.PID)
	if err != nil || binding.Scope != "" && binding.Scope != scope {
		return binding, false
	}
	if len(binding.Processes) != 0 && binding.Processes[binding.PID] == "" {
		return binding, false
	}
	token := snapshot[binding.PID].Token
	if token == "" || binding.Processes[binding.PID] != "" && binding.Processes[binding.PID] != token {
		return binding, false
	}
	created, err := strconv.ParseInt(binding.Created, 10, 64)
	started, startErr := initialProcessStartedMS(token)
	if err != nil || startErr != nil || started < created*1000-2000 || started > created*1000+2000 {
		return binding, false
	}
	owned := descendantProcesses(snapshot, binding.PID)
	provider := 0
	for pid := range owned {
		proc := filepath.Join("/proc", strconv.Itoa(pid))
		executable, err := os.Readlink(filepath.Join(proc, "exe"))
		if err != nil || filepath.Base(strings.TrimSuffix(executable, " (deleted)")) != "codex" {
			continue
		}
		command, err := os.ReadFile(filepath.Join(proc, "cmdline"))
		if err != nil || len(command) > 1<<20 {
			return binding, false
		}
		matches := false
		for _, arg := range strings.Split(string(command), "\x00") {
			matches = matches || arg == prompt
		}
		if !matches {
			continue
		}
		environment, envErr := os.ReadFile(filepath.Join(proc, "environ"))
		if envErr != nil {
			return binding, false
		}
		launch, pane := false, false
		for _, value := range strings.Split(string(environment), "\x00") {
			launch = launch || value == "ROAMI_AGENT_LAUNCH="+launchHash
			pane = pane || value == "TMUX_PANE="+binding.Pane
		}
		if !launch || !pane {
			return binding, false
		}
		cwd, err := filepath.EvalSymlinks(filepath.Join(proc, "cwd"))
		birth, birthErr := initialProcessStartedMS(snapshot[pid].Token)
		if err != nil || cwd != binding.Directory || birthErr != nil || birth < started || birth > sourceMS+2000 || provider != 0 {
			return binding, false
		}
		provider = pid
	}
	if provider == 0 {
		return binding, false
	}
	// These are newly observed residents, never a reconstruction of a historical baseline.
	binding.Scope, binding.Processes, binding.ForeignProcesses = scope, map[int]string{binding.PID: token, provider: snapshot[provider].Token}, map[int]string{}
	for pid, token := range scoped {
		if binding.Processes[pid] == token {
			continue
		}
		if !codexCodeModeHost(binding, snapshot, pid) {
			return binding, false
		}
		binding.Processes[pid] = token
	}
	return binding, true
}
