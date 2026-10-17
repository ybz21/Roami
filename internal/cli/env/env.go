package env

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

type entry struct {
	Key   string `json:"key"`
	Value string `json:"value"`
}

func Run(rt runtime.Runtime, args []string, w io.Writer) error {
	if err := rt.EnsureDirs(); err != nil {
		return err
	}
	subcmd := "list"
	if len(args) > 0 {
		subcmd = args[0]
		args = args[1:]
	}
	switch subcmd {
	case "ls", "list":
		if len(args) > 0 && args[0] == "--json" {
			return ListJSON(rt, w)
		}
		return ListText(rt, w)
	case "--json":
		return ListJSON(rt, w)
	case "set":
		if len(args) < 1 {
			return fmt.Errorf("usage: roami session env set KEY=VALUE")
		}
		return Set(rt, args[0], w)
	case "rm", "del", "delete":
		if len(args) < 1 {
			return fmt.Errorf("usage: roami session env rm KEY")
		}
		return Remove(rt, args[0], w)
	case "clear":
		return Clear(rt, w)
	case "push":
		return Push(rt, w)
	default:
		if strings.Contains(subcmd, "=") {
			return Set(rt, subcmd, w)
		}
		return fmt.Errorf("unknown subcommand: env %s", subcmd)
	}
}

func ListJSON(rt runtime.Runtime, w io.Writer) error {
	entries := []entry{}
	for _, line := range readEnvLines(rt) {
		k, v, ok := strings.Cut(line, "=")
		if ok {
			entries = append(entries, entry{Key: k, Value: v})
		}
	}
	return json.NewEncoder(w).Encode(entries)
}

// ListText prints the global env vars (mirrors _env_list).
func ListText(rt runtime.Runtime, w io.Writer) error {
	lines := readEnvLines(rt)
	if len(lines) == 0 {
		ui.Info(w, "无全局环境变量")
		return nil
	}
	p := ui.P()
	fmt.Fprintln(w)
	fmt.Fprintf(w, "  %s %s\n\n", ui.Bold("全局环境变量"), ui.Dim("("+rt.EnvFile+")"))
	for _, line := range lines {
		k, v, _ := strings.Cut(line, "=")
		fmt.Fprintf(w, "    %s%s%s=%s%s%s\n", p.Green, k, p.Reset, p.Dim, v, p.Reset)
	}
	fmt.Fprintln(w)
	return nil
}

func Set(rt runtime.Runtime, kv string, w io.Writer) error {
	if !strings.Contains(kv, "=") {
		return fmt.Errorf("usage: roami session env set KEY=VALUE")
	}
	key, _, _ := strings.Cut(kv, "=")
	lines := readEnvLines(rt)
	out := make([]string, 0, len(lines)+1)
	for _, line := range lines {
		k, _, ok := strings.Cut(line, "=")
		if ok && k == key {
			continue
		}
		out = append(out, line)
	}
	out = append(out, kv)
	if err := os.WriteFile(rt.EnvFile, []byte(strings.Join(out, "\n")+"\n"), 0o644); err != nil {
		return err
	}
	_, err := fmt.Fprintf(w, "设置 %s\n", kv)
	return err
}

func Remove(rt runtime.Runtime, key string, w io.Writer) error {
	if _, err := os.Stat(rt.EnvFile); err != nil {
		_, err := fmt.Fprintln(w, "无环境变量配置")
		return err
	}
	lines := readEnvLines(rt)
	out := make([]string, 0, len(lines))
	for _, line := range lines {
		k, _, ok := strings.Cut(line, "=")
		if ok && k == key {
			continue
		}
		out = append(out, line)
	}
	if err := os.WriteFile(rt.EnvFile, []byte(strings.Join(out, "\n")+"\n"), 0o644); err != nil {
		return err
	}
	_, err := fmt.Fprintf(w, "已删除 %s\n", key)
	return err
}

func Clear(rt runtime.Runtime, w io.Writer) error {
	if err := os.RemoveAll(rt.EnvFile); err != nil {
		return err
	}
	_, err := fmt.Fprintln(w, "全局环境变量已清空")
	return err
}

// Push injects the env file into every live session (mirrors _env_push).
func Push(rt runtime.Runtime, w io.Writer) error {
	sessions := rt.Sessions()
	if len(sessions) == 0 {
		ui.Info(w, "没有活跃会话")
		return nil
	}
	if len(rt.EnvPairs()) == 0 {
		ui.Info(w, "无环境变量可推送")
		return nil
	}
	for _, sess := range sessions {
		rt.InjectEnv(sess)
		ui.Ok(w, "已推送到 %s", ui.Bold(sess))
	}
	return nil
}

func readEnvLines(rt runtime.Runtime) []string {
	b, err := os.ReadFile(rt.EnvFile)
	if err != nil {
		return nil
	}
	var lines []string
	for _, line := range strings.Split(string(b), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		lines = append(lines, line)
	}
	return lines
}
