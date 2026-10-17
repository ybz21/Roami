// 会话 ↔ Claude 对话 id：每一轮扫描按**事实**对账，不再「盯着目录等新文件冒出来」。
//
// 从前的做法是：看见某会话刚开始跑 claude，就记下此刻目录里有哪些对话文件，等一份新文件出现
// 再认领——只认第一次、只看归属目录、后端重启后正在跑的一律认不得、没开浏览器时起的也认不得。
// 于是台账里有的会话有 id 有的没有，重启后有的接得回有的接不回。
//
// 现在事实来自 claude 进程自己：命令行里带的 --resume <id>，或者它启动之后在自己 cwd 的项目夹里
// 写的那份文件（claude-transcript-pick.go 的规则，和对话视图挑文件用的是同一条）。每一轮都算一遍，
// 算出来的和上次写进台账的不一样就更新。对不上的（同目录同时跑两个、还没说过话）先空着，下一轮再看。
// 重开会话、claude 停了再起、Roami 重启、没开浏览器——下一轮都能对上。
package api

import (
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/ybz21/Roami/backend/ttmux"
)

// agentProc 一个正在跑 agent 的会话：哪种 agent、进程 cwd、进程 pid。
type agentProc struct {
	Kind string
	Dir  string
	Pid  int
}

type agentLinker struct {
	mu     sync.Mutex
	linked map[string]string // 会话 → 已写进台账的对话 id（进程内缓存，别每轮都 exec CLI）
}

func newAgentLinker() *agentLinker { return &agentLinker{linked: map[string]string{}} }

// projectDirFor 给出某工作目录对应的 Claude Code 对话目录（~/.claude/projects/<cwd 转义>）。变量是留给测试注入的。
var projectDirFor = func(dir string) string {
	home, err := os.UserHomeDir()
	if err != nil || dir == "" {
		return ""
	}
	return filepath.Join(home, ".claude", "projects", encodeProject(dir))
}

// 进程信息的两个读法也做成变量：测试里没有真进程。
var (
	procArgvOf  = processArgv
	procStartOf = processStart
)

// argvSessionID 命令行里明写的对话 id（--resume <id> / -r <id>）。
func argvSessionID(argv []string) string {
	for i, a := range argv {
		if (a == "--resume" || a == "-r") && i+1 < len(argv) && uuidLike.MatchString(argv[i+1]) {
			return argv[i+1]
		}
	}
	return ""
}

// reconcile 对一轮扫描结果对账：procs 是每个会话正在跑的 agent 进程，link 把关联落台账。
func (l *agentLinker) reconcile(procs map[string]agentProc, link func(sess, uuid, kind string)) {
	l.mu.Lock()
	defer l.mu.Unlock()
	// 同一个 cwd 里跑着几个 claude：多于一个时靠文件猜不准，只认命令行里明写的 id
	perDir := map[string]int{}
	for _, p := range procs {
		if p.Kind == "claude" && p.Dir != "" {
			perDir[p.Dir]++
		}
	}
	for sess, p := range procs {
		if p.Kind != "claude" || p.Dir == "" {
			continue
		}
		argv := procArgvOf(p.Pid)
		uuid := argvSessionID(argv)
		if uuid == "" && perDir[p.Dir] == 1 {
			if f := pickTranscript(projectDirFor(p.Dir), argv, procStartOf(p.Pid)); f != "" {
				uuid = strings.TrimSuffix(filepath.Base(f), ".jsonl")
			}
		}
		if uuid == "" || l.linked[sess] == uuid {
			continue
		}
		l.linked[sess] = uuid
		link(sess, uuid, "claude")
	}
	// 不跑 claude 了（关了 / 退出了 / 会话没了）：忘掉，下次再起从头认
	for sess := range l.linked {
		if procs[sess].Kind != "claude" {
			delete(l.linked, sess)
		}
	}
}

// linkAgentSession 把关联落进台账。sessions 表归 CLI 写（单写者），所以走子命令。
// 记不上不是错误：空着顶多重开时给个空壳。
func (a *API) linkAgentSession(sess, uuid, kind string) {
	if out, err := a.TT.Run("db", "link-agent", sess, uuid, kind); err != nil {
		log.Printf("关联会话对话失败 %s → %s (%s): %s", sess, uuid, kind, ttmux.StripANSI(out))
	}
}
