package modelplugins

import (
	"errors"
	"os/exec"
	"path/filepath"
	"strings"
)

type SandboxPaths struct{ Bun, Runtime, Package, State, EgressSocket, Unit string }

// SandboxCommand requires both a mount/network jail and cgroup resource limits.
func SandboxCommand(p SandboxPaths) (*exec.Cmd, error) {
	for _, value := range []string{p.Bun, p.Runtime, p.Package, p.State, p.EgressSocket} {
		if !filepath.IsAbs(value) {
			return nil, errors.New("MODEL_PLUGIN_SANDBOX_UNAVAILABLE")
		}
	}
	if !strings.HasPrefix(p.Unit, "roami-model-plugin-") || strings.ContainsAny(p.Unit, "/\\ \t\r\n") {
		return nil, errors.New("MODEL_PLUGIN_SANDBOX_UNAVAILABLE")
	}
	bwrap, err := exec.LookPath("bwrap")
	if err != nil {
		return nil, errors.New("MODEL_PLUGIN_SANDBOX_UNAVAILABLE")
	}
	systemd, err := exec.LookPath("systemd-run")
	if err != nil {
		return nil, errors.New("MODEL_PLUGIN_SANDBOX_UNAVAILABLE")
	}
	args := []string{"--user", "--scope", "--quiet", "--unit=" + p.Unit, "-p", "MemoryMax=512M", "-p", "TasksMax=64", "-p", "CPUQuota=100%", "--", bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv", "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/etc", "--ro-bind", "/etc/ssl/certs", "/etc/ssl/certs", "--ro-bind", p.Bun, "/runtime/bun", "--ro-bind", p.Runtime, "/runtime/host", "--ro-bind", p.Package, "/plugin", "--bind", p.State, "/state", "--ro-bind", p.EgressSocket, "/run/model-egress.sock", "--chdir", "/state", "--setenv", "HOME", "/state", "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HTTP_PROXY", "http://127.0.0.1:18080", "--setenv", "HTTPS_PROXY", "http://127.0.0.1:18080", "--setenv", "DOUBAO_WORK_HOME", "/state/doubao-work", "/runtime/bun", "--no-install", "--smol", "--preload", "/runtime/host/egress-preload.mjs", "/runtime/host/magpie-host.js"}
	return exec.Command(systemd, args...), nil
}
