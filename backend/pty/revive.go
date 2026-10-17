package pty

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/ybz21/Roami/backend/ttmux"
)

// 会话懒恢复：attach 一个 tmux 里已经不存在的会话时，先问台账认不认得它。
//
// 机器重启带走 tmux server，但带不走台账。以前这里一律回 4404「会话已不存在」，
// 于是重启后所有终端标签集体失效，用户看到的就是「会话全消失了」。现在多问一句：
// 台账说它只是**被重启带走的**，就当场按台账重开一个壳（有 agent 对话 id 的还接回原对话），
// 然后照常 attach 下去。
//
// 这个位置能覆盖所有入口——点会话列表、从 URL 还原旧标签、手机上点开，
// 全都要走这条 WebSocket 升级，所以前端几乎不用改。
// 见 docs/design/reliability/session-restore.html。

// reviveLocks 按会话名串行化。手机和桌面同时点开同一个休眠会话时，
// 两个 WS 会同时发现「tmux 里没有」并各恢复一次，建出两个会话去抢同一份 transcript。
// CLI 那边也有一道进程内锁，这里统一串行化来自终端的恢复请求。
var reviveLocks sync.Map // session name -> *sync.Mutex

func reviveLock(name string) *sync.Mutex {
	m, _ := reviveLocks.LoadOrStore(name, &sync.Mutex{})
	return m.(*sync.Mutex)
}

// reviveTimeout 恢复一个会话最多等多久。建 tmux 会话是毫秒级的，
// 给到 20 秒是为了容忍 meta.db 正好被别的写操作锁住。
const reviveTimeout = 20 * time.Second

// reviveDormant 尝试把一个休眠会话变回活会话，返回**新**会话名。
//
// ok=false 表示台账也不认得它（或它是被显式 kill 的、原目录没了）——
// 那就是真的没了，调用方照旧回 4404。
func reviveDormant(name string) (string, bool) {
	if name == "" {
		return "", false
	}
	mu := reviveLock(name)
	mu.Lock()
	defer mu.Unlock()

	// 拿到锁后再看一眼：等锁这段时间里另一个客户端可能已经恢复好了。
	// 那种情况下会话名已经变了，靠 CLI 的 restored_from 反查回来（它内部同样做了这一步）。
	if sessionExists(name) {
		return name, true
	}

	out, err := ttmuxRun(reviveTimeout, "db", "revive", name, "--json")
	if err != nil {
		return "", false
	}
	var res struct {
		Session string `json:"session"`
	}
	if json.Unmarshal([]byte(lastJSONLine(out)), &res) != nil || res.Session == "" {
		return "", false
	}
	return res.Session, true
}

// ttmuxBin 是 CLI 的可执行名。与后端别处保持一致：TTMUX_BIN 兼容外部适配，默认使用进程内核心。
func ttmuxBin() string {
	if b := strings.TrimSpace(os.Getenv("TTMUX_BIN")); b != "" {
		return b
	}
	return "roami"
}

func ttmuxRun(timeout time.Duration, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	return ttmux.New(ttmuxBin()).RunCtx(ctx, args...)
}

// lastJSONLine 取输出里最后一行 JSON。CLI 偶尔会在 JSON 前面打一行提示，
// 直接 Unmarshal 整个输出会失败。
func lastJSONLine(out string) string {
	lines := strings.Split(strings.TrimSpace(out), "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		if s := strings.TrimSpace(lines[i]); strings.HasPrefix(s, "{") {
			return s
		}
	}
	return ""
}
