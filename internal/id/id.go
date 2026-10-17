// Package id 生成 Roami 的可读实例 id：`YYYY-MMDD-HHMM-<rand4>`（如 2026-0728-1113-asbd）。
// 蜂群 id 一直是这个格式，抽出来给全 CLI 共用，别再各写各的。
package id

import (
	"crypto/rand"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const charset = "abcdefghijklmnopqrstuvwxyz0123456789"

var re = regexp.MustCompile(`^[0-9]{4}-[0-9]{4}-[0-9]{4}-[a-z0-9]{4}$`)

// NewAt 用给定时刻生成 id（调用方通常传 rt.Now，测试可注入固定时钟）。
func NewAt(now time.Time) string {
	b := make([]byte, 4)
	if _, err := rand.Read(b); err == nil {
		for i := range b {
			b[i] = charset[int(b[i])%len(charset)]
		}
	} else {
		for i := range b {
			b[i] = 'a'
		}
	}
	return now.Format("2006-0102-1504") + "-" + string(b)
}

// New 用当前时刻生成 id。
func New() string { return NewAt(time.Now()) }

// ForSession 把 tmux 的「会话创建时刻 + session_id」派生成同款可读 id：
// 2026-0728-1150-0142。**不是第二个身份**——它与 `$142` 一一对应、可反解，
// 只是给人看的写法：会话真正的内部键仍是 tmux session_id（改名不变、server 内唯一）。
// 后缀取 session_id 的数字部分转 36 进制补到 4 位（4 位够到 167 万个会话）。
func ForSession(createdUnix int64, tmuxID string) string {
	n, ok := sessionSeq(tmuxID)
	if !ok || createdUnix <= 0 {
		return tmuxID // 数据不全就原样给 tmux id，别编一个假的出来
	}
	return time.Unix(createdUnix, 0).Format("2006-0102-1504") + "-" + base36pad4(n)
}

// sessionSeq 取 `$142` 里的数字部分。
func sessionSeq(tmuxID string) (uint64, bool) {
	digits := strings.TrimPrefix(strings.TrimSpace(tmuxID), "$")
	if digits == "" {
		return 0, false
	}
	n, err := strconv.ParseUint(digits, 10, 64)
	if err != nil {
		return 0, false
	}
	return n, true
}

func base36pad4(n uint64) string {
	s := strconv.FormatUint(n, 36)
	for len(s) < 4 {
		s = "0" + s
	}
	return s
}

// Valid 判断字符串是否本格式的 id。
func Valid(s string) bool { return re.MatchString(s) }

// UUID 生成一个 v4 UUID。
//
// 用处只有一个：Claude Code 的 --session-id 要求合法 UUID。我们自己指定它，
// 「哪份 transcript 属于哪个会话」就由构造保证，不用靠 cwd + 最新文件去猜
// （那个猜法在会话死后必然失准——同目录的别的会话会赢）。
func UUID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return ""
	}
	b[6] = (b[6] & 0x0f) | 0x40 // version 4
	b[8] = (b[8] & 0x3f) | 0x80 // variant 10
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}
