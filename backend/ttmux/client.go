// Package ttmux adapts backend requests to the in-process session core.
// An explicitly configured external CLI remains available for compatibility.
package ttmux

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"github.com/ybz21/Roami/internal/cli"
	"github.com/ybz21/Roami/internal/tmuxruntime"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
)

var ansiRE = regexp.MustCompile(`\x1b\[[0-9;]*[a-zA-Z]`)

type Client struct {
	Bin string
}

func New(bin string) *Client { return &Client{Bin: bin} }

// Run 执行 ttmux 子命令，返回合并的 stdout/stderr。
func (c *Client) Run(args ...string) (string, error) {
	return c.RunCtx(context.Background(), args...)
}

// RunCtx 同 Run，但可被 context 取消/超时。
//
// 启动期的握手必须用它：`Run` 没有超时，一个卡住的 ttmux（比如它自己在等一把
// 数据库锁）会把整个 server 的启动挂死。
func (c *Client) RunCtx(ctx context.Context, args ...string) (string, error) {
	if err := operationError(args); err != nil {
		return "", err
	}
	if (c.Local() || c.roamiEntry()) && len(args) > 0 {
		switch args[0] {
		case "list-sessions", "list-panes", "display-message", "send-keys":
			rt := runtime.New()
			rt.Context = ctx
			return rt.TmuxOutput(args...)
		}
	}
	if c.Local() {
		service := app.New().WithContext(ctx).Sessions()
		if len(args) > 0 {
			switch args[0] {
			case "ls":
				if len(args) == 2 && args[1] == "--json" {
					rows, err := service.List(ctx)
					if err != nil {
						return "", err
					}
					b, err := json.Marshal(rows)
					return string(b), err
				}
			case "send":
				if len(args) >= 3 {
					return "", service.Send(ctx, args[1], strings.Join(args[2:], " "))
				}
			case "rename":
				if len(args) >= 3 {
					return "", service.Rename(ctx, args[1], strings.Join(args[2:], " "))
				}
			case "kill":
				if len(args) >= 2 {
					return "", service.Kill(ctx, args[1], slicesContain(args[2:], "--cascade"))
				}
			case "resolve":
				if len(args) >= 2 {
					row, err := service.Resolve(args[1])
					if err != nil {
						return "", err
					}
					if slicesContain(args[2:], "--json") {
						b, err := json.Marshal(row)
						return string(b), err
					}
					return row["name"], nil
				}
			case "capture":
				if len(args) >= 2 {
					lines := "200"
					if len(args) >= 4 && (args[2] == "--lines" || args[2] == "-n") {
						lines = args[3]
					}
					return service.Capture(ctx, args[1], lines)
				}
			}
		}
		var out bytes.Buffer
		err := app.New().WithContext(ctx).WithOutput(&out).Run(args)
		return out.String(), err
	}

	cmd := c.command(ctx, args)
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &out
	err := cmd.Run()
	return out.String(), err
}

// RunJSON 执行子命令，**分开**拿 stdout 与 stderr。
//
// 取 JSON 的地方必须用它：插件的日志走 stderr（SDK 的 Logf 写的
// `[roam.cron] 已添加定时任务 …`），和 stdout 混在一起，返回的就不再是 JSON——
// 浏览器只会看到「Unexpected token 'r'」，而真正发生了什么（那行日志）反被吞掉。
// 出错时两股都要：诊断信息通常正在 stderr 里。
func (c *Client) RunJSON(args ...string) (stdout, stderr string, err error) {
	if err := operationError(args); err != nil {
		return "", "", err
	}
	if c.Local() {
		out, err := c.RunCtx(context.Background(), args...)
		if err != nil {
			return out, fmt.Sprint(err), err
		}
		return out, "", nil
	}

	cmd := c.command(context.Background(), args)
	var o, e bytes.Buffer
	cmd.Stdout = &o
	cmd.Stderr = &e
	err = cmd.Run()
	return o.String(), e.String(), err
}

// StripANSI 去除文本中的 ANSI 颜色转义。
func StripANSI(s string) string { return ansiRE.ReplaceAllString(s, "") }

func (c *Client) Local() bool {
	self, _ := os.Executable()
	return c.Bin == self || c.Bin == "roami"
}

func slicesContain(args []string, word string) bool {
	for _, a := range args {
		if a == word {
			return true
		}
	}
	return false
}

func (c *Client) CreateSession(ctx context.Context, label, dir string) (string, error) {
	result, err := app.New().WithContext(ctx).Sessions().Create(ctx, runtime.CreateOpts{Label: label, Dir: dir}, false)
	return result.Session, err
}

func operationError(args []string) error {
	if len(args) > 0 {
		switch args[0] {
		case "kill-server", "killall", "kill-session", "source-file", "run-shell":
			return fmt.Errorf("unsupported session operation %q", args[0])
		}
	}
	return nil
}

func (c *Client) roamiEntry() bool {
	base := filepath.Base(c.Bin)
	return base == "roami" || strings.HasPrefix(base, "roami-")
}

func (c *Client) command(ctx context.Context, args []string) *exec.Cmd {
	if c.roamiEntry() {
		args = append([]string{"session"}, args...)
	}
	return exec.CommandContext(ctx, c.Bin, args...)
}
