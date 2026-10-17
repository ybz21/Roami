package agent

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

func init() { Register(codex{}) }

// codex 是 OpenAI Codex CLI。
//
// 它与 claude 的关键差别：**启动时没法指定对话 id**。所以 Roami 只能事后认——
// 它把每段对话写成 ~/.codex/sessions/YYYY/MM/DD/rollout-<时间>-<uuid>.jsonl，
// uuid 就在文件名里。
//
// 代码里一度写着「codex 没有对应参数，忽略」，于是 codex 会话恢复出来永远只有壳。
// 那句话在写下时是对的，但 codex 后来加了 `codex resume <SESSION_ID>`——
// 假设过期了没人回头改，是这类分支最容易烂掉的地方。
type codex struct{}

func (codex) Kind() string        { return "codex" }
func (codex) DisplayName() string { return "Codex" }
func (codex) Bin() string         { return "codex" }

// 没有 --session-id 这类参数：id 由它自己生成，只能事后从 rollout 文件名认。
func (codex) PinsConversationID() bool { return false }

func (codex) InteractiveArgs(opt StartOpts) []string {
	var a []string
	if opt.Model != "" {
		a = append(a, "-m", opt.Model)
	}
	// ConvID 故意忽略：这一型指定不了，硬塞一个参数上去只会让它起不来。
	// Permission 也忽略：codex 交互式没有权限档的概念。
	return a
}

func (codex) OneShotArgs(opt StartOpts) []string {
	a := []string{"exec", "--skip-git-repo-check"}
	if opt.Model != "" {
		a = append(a, "-m", opt.Model)
	}
	// codex 只有一个「全放开」开关，没有档位。Roami 这边的 auto 和
	// dangerously-skip-permissions 都映射到它——都是「别停下来问」的意思。
	if opt.Permission == "dangerously-skip-permissions" || opt.Permission == "auto" {
		a = append(a, "--dangerously-bypass-approvals-and-sandbox")
	}
	// MaxTurns 支持不了，忽略。
	//
	// 末尾这个 `-` 是「从 stdin 读 prompt」，claude 那边由 -p 隐含。
	return append(a, "-")
}

func (c codex) ResumeCommand(convID string) string {
	if strings.TrimSpace(convID) == "" {
		return ""
	}
	// `codex resume <SESSION_ID>`：SESSION_ID 收 UUID 或会话名，UUID 优先。
	return c.Bin() + " resume " + convID
}

// rolloutRE 从 rollout-2026-08-08T09-33-53-019fdf01-....jsonl 里抠出末尾的 uuid。
var rolloutRE = regexp.MustCompile(`rollout-.*-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$`)

// ConversationDir 不知道：rollout 文件名里没有 cwd，session_meta 里那个字段没核实过格式，
// 猜错会把会话建到别的目录去。退回台账记的归属目录。
func (codex) ConversationDir(string) string { return "" }

// DetectConversationID 在 ~/.codex/sessions 下找最近写过的那段对话。
//
// **这是推断，不是事实**：codex 的 rollout 文件名里没有 cwd，同一时间在别处
// 开的 codex 会赢。所以只在「刚拉起、且这台机器上没有别的 codex 在跑」时调用，
// 认不出就老实返回空串——宁可这个会话恢复出来只有壳，也别接回别人的对话。
func (codex) DetectConversationID(cwd string) string {
	root := sessionsRoot()
	if root == "" {
		return ""
	}
	type hit struct {
		path string
		mod  int64
	}
	var hits []hit
	_ = filepath.WalkDir(root, func(p string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(p, ".jsonl") {
			return nil
		}
		if !rolloutRE.MatchString(p) {
			return nil
		}
		fi, e := d.Info()
		if e != nil {
			return nil
		}
		hits = append(hits, hit{p, fi.ModTime().UnixNano()})
		return nil
	})
	if len(hits) == 0 {
		return ""
	}
	sort.Slice(hits, func(i, j int) bool { return hits[i].mod > hits[j].mod })
	m := rolloutRE.FindStringSubmatch(hits[0].path)
	if len(m) < 2 {
		return ""
	}
	return m[1]
}

func sessionsRoot() string {
	if v := strings.TrimSpace(os.Getenv("CODEX_HOME")); v != "" {
		return filepath.Join(v, "sessions")
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".codex", "sessions")
}
