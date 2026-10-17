// delegate.go 实现管家的打包派活命令(设计 §4.4 委派协议):一步完成
// worker 会话创建、结束回流登记、tasks/ 台账铺底,并把「回报契约」拼进
// worker 的开工 prompt——管家只需要写 BRIEF、收到结束通知后读 RESULT.md 验收。
package im

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

func delegate(ctx *sdk.Ctx, args map[string]string) (any, error) {
	name, dir := strings.TrimSpace(args["name"]), strings.TrimSpace(args["dir"])
	chat := strings.TrimSpace(args["chat"])
	task := args["task"]
	if bf := args["brief-file"]; bf != "" {
		b, err := os.ReadFile(bf)
		if err != nil {
			return nil, fmt.Errorf("brief-file: %w", err)
		}
		task = string(b)
	}
	if name == "" || dir == "" || strings.TrimSpace(task) == "" {
		return nil, fmt.Errorf("usage: roami plugin run im-bridge.delegate --name w-<主题> --dir <绝对路径> --task '…'|--brief-file <文件> [--chat <chat_id>] [--provider claude|codex] [--interactive]")
	}
	if !filepath.IsAbs(dir) {
		return nil, fmt.Errorf("delegate: --dir 必须是绝对路径,got %q", dir)
	}
	if !strings.HasPrefix(name, "im-") {
		name = "im-" + name
	}
	interactive := args["interactive"] == "true"

	// tasks/<name>/ 台账铺底:BRIEF 是委派内容,RESULT.md 是 worker 的交付物
	taskDir := filepath.Join(workspaceDir(ctx), "tasks", strings.TrimPrefix(name, "im-"))
	if err := os.MkdirAll(taskDir, 0o755); err != nil {
		return nil, err
	}
	if err := os.WriteFile(filepath.Join(taskDir, "BRIEF.md"), []byte(task), 0o644); err != nil {
		return nil, err
	}
	resultPath := filepath.Join(taskDir, "RESULT.md")

	provider := args["provider"]
	if provider == "" {
		provider = ctx.Config["provider"]
	}
	sess, err := ctx.AgentSpawn(sdk.SpawnReq{
		Provider:    provider,
		Prompt:      task + workerContract(chat, name, resultPath, interactive),
		SessionName: name,
		Workdir:     dir,
		Interactive: interactive,
		Labels: map[string]string{
			"im:worker":   "1",
			"im:chat":     chat,
			"im:task_dir": taskDir,
			"role":        "im-task",
		},
	})
	if err != nil {
		return nil, err
	}
	meta := fmt.Sprintf("session: %s\nstarted: %s\nworkdir: %s\nchat: %s\ninteractive: %v\n",
		sess, time.Now().Format("2006-01-02 15:04:05"), dir, chat, interactive)
	_ = os.WriteFile(filepath.Join(taskDir, "META.txt"), []byte(meta), 0o644)
	ctx.Logf("delegated worker %s (dir=%s interactive=%v)", sess, dir, interactive)
	return map[string]string{"session": sess, "taskDir": taskDir, "result": resultPath}, nil
}

// workerContract 是拼在 BRIEF 之后的回报契约(设计 §4.4 五要素中的回报与结束)。
func workerContract(chat, sess, resultPath string, interactive bool) string {
	var b strings.Builder
	b.WriteString("\n\n---\n# 回报契约(必须遵守)\n")
	fmt.Fprintf(&b, "1. 最终结果写到 %s(结构化:结论、改动清单、PR 链接、遗留问题)——这是验收的唯一依据;\n", resultPath)
	if chat != "" {
		fmt.Fprintf(&b, "2. 关键里程碑或阻塞可直接告知用户: roami plugin run im-bridge.send --chat %s --text '…'(勿滥用,普通进度写 RESULT.md 即可);\n", chat)
	} else {
		b.WriteString("2. 不要直接给用户发消息,一切经 RESULT.md 汇报;\n")
	}
	if interactive {
		fmt.Fprintf(&b, "3. 全部完成并写好 RESULT.md 后,执行 Bash 命令 tmux kill-session -t %s 结束本会话——这就是交活信号。\n", sess)
	} else {
		b.WriteString("3. 输出完成即视为交活,无需其他收尾。\n")
	}
	return b.String()
}
