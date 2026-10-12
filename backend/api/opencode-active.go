package api

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

type openCodeAPIResponse struct {
	Data json.RawMessage `json:"data"`
}

func openCodeCommand(ctx context.Context, binary string, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, binary, append([]string{"api"}, args...)...)
	return cmd.Output()
}

func openCodeActiveSessions(output []byte) ([]string, error) {
	var response openCodeAPIResponse
	if err := json.Unmarshal(output, &response); err != nil {
		return nil, err
	}
	var active map[string]json.RawMessage
	if err := json.Unmarshal(response.Data, &active); err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(active))
	for id := range active {
		if strings.HasPrefix(id, "ses_") {
			ids = append(ids, id)
		}
	}
	sort.Strings(ids)
	return ids, nil
}

func openCodeSessionDirectory(output []byte) (string, error) {
	var response struct {
		Data struct {
			Location struct {
				Directory string `json:"directory"`
			} `json:"location"`
		} `json:"data"`
	}
	if err := json.Unmarshal(output, &response); err != nil {
		return "", err
	}
	if !filepath.IsAbs(response.Data.Location.Directory) {
		return "", fmt.Errorf("OpenCode session has no absolute directory")
	}
	return filepath.Clean(response.Data.Location.Directory), nil
}

// OpenCode 的后台服务可继续执行已离开 TUI 的会话；终端抓屏此时只显示 New session。
func scanOpenCodeActive(procs map[string]agentProc, dirsByID map[string]string) map[string]bool {
	candidates := map[string][]string{}
	binary := ""
	for name, proc := range procs {
		if proc.Kind != "opencode" {
			continue
		}
		candidates[filepath.Clean(proc.Dir)] = append(candidates[filepath.Clean(proc.Dir)], name)
		if binary == "" {
			binary, _ = os.Readlink(filepath.Join("/proc", strconv.Itoa(proc.Pid), "exe"))
		}
	}
	if len(candidates) == 0 || binary == "" {
		return nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	output, err := openCodeCommand(ctx, binary, "session.active")
	if err != nil {
		return nil
	}
	ids, err := openCodeActiveSessions(output)
	if err != nil {
		return nil
	}
	activeDirs := make([]string, 0, len(ids))
	for _, id := range ids {
		dir := dirsByID[id]
		if dir == "" {
			output, err := openCodeCommand(ctx, binary, "session.get", "--param", "sessionID="+id)
			if err != nil {
				continue
			}
			dir, err = openCodeSessionDirectory(output)
			if err != nil {
				continue
			}
			dirsByID[id] = dir
		}
		activeDirs = append(activeDirs, dir)
	}
	return assignOpenCodePanes(candidates, activeDirs)
}

func assignOpenCodePanes(candidates map[string][]string, activeDirs []string) map[string]bool {
	for dir := range candidates {
		sort.Strings(candidates[dir])
	}
	assigned := map[string]bool{}
	for _, dir := range activeDirs {
		for _, name := range candidates[dir] {
			if !assigned[name] {
				assigned[name] = true
				break
			}
		}
	}
	return assigned
}
