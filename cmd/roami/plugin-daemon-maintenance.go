package main

import (
	"context"
	"log"
	"os/exec"
	"strings"
	"time"
)

// The web process owns plugind liveness; the CLI command is idempotent and repairs stale tmux sessions.
func maintainPluginDaemon(ctx context.Context, bin string, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	failed := false
	for {
		attempt, cancel := context.WithTimeout(ctx, 10*time.Second)
		out, err := exec.CommandContext(attempt, bin, "plugin", "daemon").CombinedOutput()
		cancel()
		if err != nil && !failed {
			log.Printf("plugind 自动维护失败: %v: %s", err, strings.TrimSpace(string(out)))
		}
		if err == nil && failed {
			log.Printf("plugind 已自动恢复")
		}
		failed = err != nil
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
