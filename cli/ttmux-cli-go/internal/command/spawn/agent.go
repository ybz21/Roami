package spawn

import (
	"os/exec"

	"strings"
	"ttmux-cli-go/internal/agent"
	"ttmux-cli-go/internal/id"
)

// AgentConfig captures the knobs lib/agent.sh exposed via AGENT_* env vars.
type AgentConfig struct {
	ClaudeBin   string
	CodexBin    string
	Kind        string // agent registry kind
	Interactive bool   // resident TUI member (vs one-shot task)
	Permission  string
	Model       string
	Workdir     string
	MaxTurns    string
	// SessionUUID 让我们**指定** Claude Code 那一侧的对话 id（--session-id）。
	// 不指定的话，「哪份 transcript 属于哪个会话」只能靠 cwd + 取最新文件猜，
	// 而会话一死这个猜法就失准（同目录的别的会话会赢）。指定之后关联由构造保证，
	// 台账把它记下来，M3 的「重开并接回原对话」才有依据。codex 没有对应参数，忽略。
	SessionUUID string
}

// DefaultAgentConfig mirrors _agent_defaults.
func DefaultAgentConfig(workdir string) AgentConfig {
	return AgentConfig{
		ClaudeBin:  lookPath("claude"),
		CodexBin:   lookPath("codex"),
		Kind:       "claude",
		Permission: "dangerously-skip-permissions",
		Workdir:    workdir,
		// 每个 agent 会话都自带一个对话 id。生成成本为零，而少了它，
		// 会话死后就再也认不出「那段对话是哪一份 jsonl」。
		SessionUUID: id.UUID(),
	}
}

func lookPath(bin string) string {
	if p, err := exec.LookPath(bin); err == nil {
		return p
	}
	return bin
}

// 下面四个方法只管**通用外壳**：cd 进工作目录、bin 用哪个、prompt 怎么投喂
// （内联 heredoc / 文件走 stdin / $(cat) 注入）。**每一型自己的参数由 agent 包给**——
// 从前这里是四处 `if c.Kind == "codex"`，加一型就得把它们全找一遍。

// resolve 取这一型的实现；认不出退回默认那型，别拼出一条空命令交给 shell。
func (c AgentConfig) resolve() agent.Agent {
	if a := agent.Get(c.Kind); a != nil {
		return a
	}
	return agent.Default()
}

// bin 可执行文件：配置里指定了就用指定的（装在别处 / 用 wrapper 包了一层），
// 否则用这一型的默认名。
//
// ClaudeBin/CodexBin 是**历史字段**，只对这两型有效。新增的型直接用 a.Bin()——
// 不这么写的话它会掉进 claude 那条分支，拿到一个完全不相干的可执行名。
// 真要给新型加覆盖，该做的是把这两个字段换成 map[kind]string，而不是再加一个 case。
func (c AgentConfig) bin(a agent.Agent) string {
	if a == nil {
		return orDefault(c.ClaudeBin, "claude")
	}
	switch a.Kind() {
	case "claude":
		return orDefault(c.ClaudeBin, a.Bin())
	case "codex":
		return orDefault(c.CodexBin, a.Bin())
	}
	return a.Bin()
}

func (c AgentConfig) startOpts() agent.StartOpts {
	return agent.StartOpts{
		ConvID:     c.SessionUUID,
		Model:      c.Model,
		Permission: c.Permission,
		MaxTurns:   c.MaxTurns,
	}
}

// prefix 拼出 `cd '<工作目录>' && <bin> <参数…>`，参数由这一型自述。
func (c AgentConfig) prefix(interactive bool) string {
	a := c.resolve()
	var args []string
	if a != nil {
		if interactive {
			args = a.InteractiveArgs(c.startOpts())
		} else {
			args = a.OneShotArgs(c.startOpts())
		}
	}
	b := "cd '" + c.Workdir + "' && " + c.bin(a)
	if len(args) > 0 {
		b += " " + strings.Join(args, " ")
	}
	return b
}

// Command builds the shell command line that launches the agent, mirroring
// _agent_cmd → _agent_claude_cmd / _agent_codex_cmd.
func (c AgentConfig) Command(task string) string {
	if c.Interactive {
		return c.prefix(true) + " " + shellQuote(task)
	}
	if a, ok := c.resolve().(interface{ OneShotPromptArg() bool }); ok && a.OneShotPromptArg() {
		return c.prefix(false) + " " + shellQuote(task)
	}
	return c.prefix(false) + heredoc(task)
}

// CommandFromPromptFile builds the one-shot launch command with the task fed
// from a file on stdin. tmux send-keys 有命令长度上限(整段 diff 内联会报
// "command too long"),经会话拉起 Agent 的调用方必须用这个短命令形态。
func (c AgentConfig) CommandFromPromptFile(path string) string {
	if a, ok := c.resolve().(interface{ OneShotPromptArg() bool }); ok && a.OneShotPromptArg() {
		return c.prefix(false) + ` "$(cat ` + shellQuote(path) + `)"`
	}
	return c.prefix(false) + " < " + shellQuote(path)
}

// InteractiveFromPromptFile builds the interactive-TUI launch command with the
// initial prompt read from a file("$(cat …)" 注入,同 swarm members 的手法:
// 多行 prompt 内联会被 send-keys 的换行当回车拆碎)。
func (c AgentConfig) InteractiveFromPromptFile(path string) string {
	return c.prefix(true) + ` "$(cat ` + shellQuote(path) + `)"`
}

// heredoc appends a `<<'TTMUX_TASK_EOF'` block carrying the task verbatim,
// avoiding any quoting of the prompt body (matches lib/agent.sh).
func heredoc(task string) string {
	return " <<'TTMUX_TASK_EOF'\n" + task + "\nTTMUX_TASK_EOF"
}

// shellQuote single-quotes a string POSIX-safely (replacement for printf %q in
// the interactive path; single-quote wrapping is portable across shells).
func shellQuote(s string) string {
	return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'"
}

func orDefault(v, def string) string {
	if v == "" {
		return def
	}
	return v
}
