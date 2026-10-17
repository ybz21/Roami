package spawn

import (
	"os"
	"os/exec"
	"strings"
	"syscall"
	"time"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// LaunchAutoconfirm detaches a background poller that clicks through claude's
// first-run dialogs (trust folder / bypass permissions), mirroring the
// `setsid bash -c _spawn_autoconfirm` trick in lib/spawn.sh. It re-execs this
// binary's hidden `__autoconfirm` subcommand in a new session so it survives
// the parent command returning.(插件 agent.spawn 的交互会话也用它,否则
// 首次打开的目录会卡在 trust 确认上)
func LaunchAutoconfirm(rt runtime.Runtime, sess string) {
	self, err := os.Executable()
	if err != nil {
		return
	}
	cmd := exec.Command(self, "__autoconfirm", sess)
	cmd.Stdin = nil
	cmd.Stdout = nil
	cmd.Stderr = nil
	cmd.Env = os.Environ()
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	_ = cmd.Start()
	if cmd.Process != nil {
		_ = cmd.Process.Release()
	}
}

// RunAutoconfirm is the worker invoked by the hidden `__autoconfirm` subcommand.
func RunAutoconfirm(rt runtime.Runtime, sess string) {
	trusted, bypassed := false, false
	for i := 0; i < 30; i++ {
		time.Sleep(time.Second)
		scr, err := rt.TmuxOutput("capture-pane", "-t", sess, "-p")
		if err != nil {
			continue
		}
		if !trusted && strings.Contains(scr, "trust this folder") {
			_ = rt.Tmux("send-keys", "-t", sess, "Enter")
			trusted = true
			continue
		}
		if !bypassed && strings.Contains(scr, "Bypass Permissions mode") {
			_ = rt.Tmux("send-keys", "-t", sess, "Down", "Enter")
			bypassed = true
		}
		if trusted && bypassed {
			break
		}
	}
}
