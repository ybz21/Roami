package agentexecution

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// npm may start its configured stdio host after the initial process snapshot.
// Only the declared host and its launch shell qualify; host descendants do not.
func npmStdioHost(binding SessionBinding, snapshot map[int]paneProcess, pid int) bool {
	return npmStdioHostAt("/proc", binding, snapshot, pid, os.ReadFile, observedProcessToken)
}

func npmStdioHostAt(proc string, binding SessionBinding, snapshot map[int]paneProcess, pid int, read func(string) ([]byte, error), token func(int) string) bool {
	args := func(id int) []string {
		data, err := read(filepath.Join(proc, strconv.Itoa(id), "cmdline"))
		if err != nil {
			return nil
		}
		return strings.Split(strings.TrimRight(string(data), "\x00"), "\x00")
	}
	child, ok := snapshot[pid]
	if !ok {
		return false
	}
	shellPID, nodePID := child.Parent, pid
	childArgs := args(pid)
	if len(childArgs) == 3 && filepath.Base(childArgs[0]) == "sh" && childArgs[1] == "-c" {
		shellPID, nodePID = pid, 0
		for candidate, p := range snapshot {
			if p.Parent == pid {
				if nodePID != 0 {
					return false
				}
				nodePID = candidate
			}
		}
	}
	shell, ok := snapshot[shellPID]
	if !ok || nodePID == 0 {
		return false
	}
	launcher, ok := snapshot[shell.Parent]
	if !ok || binding.Processes[shell.Parent] != launcher.Token {
		return false
	}
	owned := false
	for current, seen := shell.Parent, map[int]bool{}; current > 0 && !seen[current]; current = snapshot[current].Parent {
		seen[current] = true
		if current == binding.PID {
			owned = true
			break
		}
	}
	if !owned {
		return false
	}
	shellArgs, nodeArgs, launcherArgs := args(shellPID), args(nodePID), args(shell.Parent)
	if len(shellArgs) != 3 || filepath.Base(shellArgs[0]) != "sh" || shellArgs[1] != "-c" || len(nodeArgs) != 2 || filepath.Base(nodeArgs[0]) != "node" || len(launcherArgs) != 1 {
		return false
	}
	launch := strings.Fields(launcherArgs[0])
	if len(launch) != 3 || launch[0] != "npm" || launch[1] != "exec" {
		return false
	}
	pkg := launch[2]
	if at := strings.LastIndexByte(pkg, '@'); at > 0 {
		pkg = pkg[:at]
	}
	bin := shellArgs[2]
	if bin == "" || strings.ContainsAny(bin, " /\\\t\n;&|$`<>()") || !filepath.IsAbs(nodeArgs[1]) || filepath.Base(nodeArgs[1]) != bin || filepath.Base(filepath.Dir(nodeArgs[1])) != ".bin" {
		return false
	}
	modules := filepath.Dir(filepath.Dir(nodeArgs[1]))
	if filepath.Base(modules) != "node_modules" {
		return false
	}
	packageRoot := filepath.Join(modules, filepath.FromSlash(pkg))
	rel, err := filepath.Rel(modules, packageRoot)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return false
	}
	raw, err := read(filepath.Join(packageRoot, "package.json"))
	if err != nil {
		return false
	}
	var manifest struct {
		Name string          `json:"name"`
		Bin  json.RawMessage `json:"bin"`
	}
	if json.Unmarshal(raw, &manifest) != nil || manifest.Name != pkg {
		return false
	}
	var bins map[string]string
	if json.Unmarshal(manifest.Bin, &bins) != nil {
		var entry string
		if json.Unmarshal(manifest.Bin, &entry) != nil || bin != filepath.Base(pkg) {
			return false
		}
		bins = map[string]string{bin: entry}
	}
	entry := bins[bin]
	if entry == "" {
		return false
	}
	expected := filepath.Clean(filepath.Join(packageRoot, entry))
	rel, err = filepath.Rel(packageRoot, expected)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return false
	}
	actualPath, err := filepath.EvalSymlinks(nodeArgs[1])
	if err != nil || actualPath != expected {
		return false
	}
	for _, id := range []int{shellPID, nodePID, shell.Parent} {
		if snapshot[id].Token == "" || token(id) != snapshot[id].Token {
			return false
		}
	}
	latest, err := read(filepath.Join(proc, strconv.Itoa(shell.Parent), "cmdline"))
	return err == nil && bytes.Equal(bytes.TrimRight(latest, "\x00"), []byte(strings.Join(launcherArgs, "\x00")))
}
