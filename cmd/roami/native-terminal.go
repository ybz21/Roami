package main

import (
	"context"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessionipc"
	tmuxrt "github.com/ybz21/Roami/internal/tmuxruntime"
)

func nativeTerminalEnabled() bool {
	v := strings.TrimSpace(strings.ToLower(os.Getenv("ROAMI_NATIVE_TERMINAL")))
	if v == "0" || v == "false" || v == "off" {
		return false
	}
	return true
}

// maybeConnectNativeTerminal enables the native roami-sessiond backend by default on all platforms.
// Set ROAMI_NATIVE_TERMINAL=0 to disable and stay on tmux; if roami-sessiond is missing or fails
// to start on Unix, it logs and falls back to tmux.
func maybeConnectNativeTerminal(roamiBin, instanceRoot string) (sessionbackend.SessionBackend, func()) {
	if !nativeTerminalEnabled() {
		return nil, func() {}
	}
	sessiondBin := resolveSessiondBin(roamiBin)
	mgr := sessionipc.NewManager(instanceRoot, sessiondBin)
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	defer cancel()
	router, err := mgr.Router(ctx, tmuxrt.New().Backend())
	if err != nil {
		log.Printf("原生终端宿主未就绪（回退 tmux）: %v", err)
		mgr.Close()
		return nil, func() {}
	}
	log.Printf("原生终端已启用（roami-sessiond=%s）", sessiondBin)
	return router, mgr.Close
}

func resolveSessiondBin(roamiBin string) string {
	if explicit := strings.TrimSpace(os.Getenv("ROAMI_SESSIOND_BIN")); explicit != "" {
		return explicit
	}
	binName := "roami-sessiond"
	if runtime.GOOS == "windows" {
		binName = "roami-sessiond.exe"
	}
	if roamiBin != "" {
		sibling := filepath.Join(filepath.Dir(roamiBin), binName)
		if _, err := os.Stat(sibling); err == nil {
			return sibling
		}
	}
	if found, err := exec.LookPath(binName); err == nil {
		return found
	}
	return ""
}
