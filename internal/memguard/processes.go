package memguard

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

type Process struct {
	PID       int    `json:"pid"`
	PPID      int    `json:"ppid"`
	Name      string `json:"name"`
	Command   string `json:"command"`
	State     string `json:"state"`
	RSS       int64  `json:"rss"`
	Swap      int64  `json:"swap"`
	Start     string `json:"start"`
	Protected bool   `json:"protected"`
}

func processStat(data string) (int, string, string, error) {
	end := strings.LastIndex(data, ")")
	if end < 0 {
		return 0, "", "", fmt.Errorf("invalid process stat")
	}
	fields := strings.Fields(data[end+1:])
	if len(fields) < 20 {
		return 0, "", "", fmt.Errorf("incomplete process stat")
	}
	parent, err := strconv.Atoi(fields[1])
	return parent, fields[0], fields[19], err
}

func readProcess(pid int) (Process, error) {
	dir := filepath.Join("/proc", strconv.Itoa(pid))
	stat, err := os.ReadFile(filepath.Join(dir, "stat"))
	if err != nil {
		return Process{}, err
	}
	parent, state, start, err := processStat(string(stat))
	if err != nil {
		return Process{}, err
	}
	status, err := os.ReadFile(filepath.Join(dir, "status"))
	if err != nil {
		return Process{}, err
	}
	p := Process{PID: pid, PPID: parent, State: state, Start: start}
	for _, line := range strings.Split(string(status), "\n") {
		key, value, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		switch key {
		case "Name":
			p.Name = strings.TrimSpace(value)
		case "VmRSS", "VmSwap":
			fields := strings.Fields(value)
			if len(fields) > 0 {
				n, _ := strconv.ParseInt(fields[0], 10, 64)
				if key == "VmRSS" {
					p.RSS = n << 10
				} else {
					p.Swap = n << 10
				}
			}
		}
	}
	command, _ := os.ReadFile(filepath.Join(dir, "cmdline"))
	if len(command) > 4096 {
		command = command[:4096]
	}
	p.Command = strings.TrimSpace(strings.ReplaceAll(string(command), "\x00", " "))
	return p, nil
}

func processScopes(panes []int) (map[string]bool, error) {
	scopes := map[string]bool{}
	if len(panes) == 0 {
		return nil, fmt.Errorf("SESSION_PROCESS_UNAVAILABLE")
	}
	for _, pid := range panes {
		dir, err := freezeDirectory(pid)
		if err != nil {
			return nil, fmt.Errorf("SESSION_PROCESS_UNAVAILABLE: %w", err)
		}
		scopes[dir] = true
	}
	return scopes, nil
}

func inProcessScopes(pid int, scopes map[string]bool) bool {
	dir := cgroupDir(pid)
	for root := range scopes {
		if dir == root || strings.HasPrefix(dir, root+"/") {
			return true
		}
	}
	return false
}

// Scope membership retains detached build daemons after their original parent exits.
func Processes(panes []int) ([]Process, error) {
	scopes, err := processScopes(panes)
	if err != nil {
		return nil, err
	}
	protected := map[int]bool{os.Getpid(): true}
	for _, pid := range panes {
		protected[pid] = true
	}
	result := []Process{}
	seen := map[int]bool{}
	for root := range scopes {
		err := filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
			if walkErr != nil {
				return walkErr
			}
			if entry.Name() != "cgroup.procs" {
				return nil
			}
			b, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			for _, value := range strings.Fields(string(b)) {
				pid, _ := strconv.Atoi(value)
				if seen[pid] || !inProcessScopes(pid, scopes) {
					continue
				}
				p, err := readProcess(pid)
				if err != nil {
					continue
				}
				p.Protected = protected[pid]
				seen[pid] = true
				result = append(result, p)
			}
			return nil
		})
		if err != nil {
			return nil, fmt.Errorf("SESSION_PROCESS_UNAVAILABLE: %w", err)
		}
	}
	sort.Slice(result, func(i, j int) bool { return result[i].PID < result[j].PID })
	return result, nil
}

func StopProcess(panes []int, pid int, start string, force bool) error {
	scopes, err := processScopes(panes)
	if err != nil {
		return err
	}
	if pid <= 1 || pid == os.Getpid() {
		return fmt.Errorf("SESSION_PROCESS_PROTECTED")
	}
	for _, root := range panes {
		if root == pid {
			return fmt.Errorf("SESSION_PROCESS_PROTECTED")
		}
	}
	return signalProcess(pid, start, force, scopes)
}
