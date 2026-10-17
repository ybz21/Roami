// Package memalert 是会话内存的看门狗：在爆之前让人知道是哪个会话在涨。
//
// L1 的内存上限管的是「爆了之后损失可控」——失控的 agent 只杀死自己。
// 这一层管的是**预防**：内存在会话列表上一直看得见，涨起来的那个自己会跳出来，
// 而不是等到某天早上发现机器又卡住了。
//
// **不主动杀**。硬顶交给内核（确定、及时、不会误判），看门狗只负责让人知道。
// 一个跑了三小时的 agent 被脚本按阈值猜杀，比 OOM 更让人恼火。
//
// 见 docs/design/reliability/memory-guard.html §06。
package memalert

import (
	"fmt"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/storage"
)

// warnPercent 预警档位：占到上限这么多就说一声。
//
// 85 是「还有余量、但趋势已经明确」的位置：L1 的软限在 75%（那里内核开始
// throttle），到 85% 说明 throttle 也没按住它。再高就没有反应时间了。
const warnPercent = 85

// Sample 一个会话此刻的内存画像。Limit=0 表示没设上限，那就无从谈起百分比。
type Sample struct {
	Session  string
	Label    string
	Cur      int64
	Peak     int64
	Limit    int64
	OOMKills int64
}

// Check 比对每个会话的内存与「已经提醒过什么」，只在状态**变化**时写通知。
//
// 去重不能只靠 plugin_notifications 那 5 分钟的 dedupe 窗口：一个失控会话涨一小时
// 就会发十几条。所以按会话把「提醒到哪儿了」记在台账上，档位没变就不再说。
func Check(db *metadb.DB, now time.Time, samples []Sample) {
	if db == nil || db.DB == nil {
		return
	}
	for _, s := range samples {
		var levelWas, oomsWas int64
		_ = db.QueryRow(`SELECT IFNULL(mem_alert_level,0), IFNULL(mem_alert_ooms,0)
			FROM sessions WHERE id=?`, s.Session).Scan(&levelWas, &oomsWas)

		// ① 撞顶被杀。这条一定要有：否则用户只会看到 agent 莫名其妙没了。
		if s.OOMKills > oomsWas {
			add(db, now, Notification{
				Type: "memory", Severity: "error",
				Title: fmt.Sprintf("会话「%s」里的进程因超出内存上限被终止", s.name()),
				Body: fmt.Sprintf("上限 %s，峰值 %s。会话本身还在，重开一个 agent 即可继续。",
					human(s.Limit), human(s.Peak)),
				Dedupe: fmt.Sprintf("mem-oom:%s:%d", s.Session, s.OOMKills),
			})
			_, _ = db.Exec(`UPDATE sessions SET mem_alert_ooms=? WHERE id=?`, s.OOMKills, s.Session)
		}

		// ② 逼近上限。跌回阈值以下会清零，于是它再涨上来时会重新提醒。
		level := int64(0)
		if s.Limit > 0 && s.Cur*100/s.Limit >= warnPercent {
			level = warnPercent
		}
		if level == levelWas {
			continue
		}
		if level > 0 {
			add(db, now, Notification{
				Type: "memory", Severity: "warning",
				Title: fmt.Sprintf("会话「%s」内存 %s / %s", s.name(), human(s.Cur), human(s.Limit)),
				Body:  "已占到上限的 85%，还在涨。撞顶时这个会话里的进程会被内核终止（其他会话不受影响）。",
				// 档位变化本就只发一次，dedupe 只是防同一轮里的重复写入。
				Dedupe: fmt.Sprintf("mem-high:%s", s.Session),
			})
		}
		_, _ = db.Exec(`UPDATE sessions SET mem_alert_level=? WHERE id=?`, level, s.Session)
	}
}

func (s Sample) name() string {
	if s.Label != "" {
		return s.Label
	}
	return s.Session
}

// Notification 与 plugin.Notification 同形（同一张表）。这里不 import plugin：
// 那个包是插件宿主，为了写一行通知把它拖进会话列表的热路径不划算。
type Notification struct {
	Type, Severity, Title, Body, Dedupe string
}

func add(db *metadb.DB, now time.Time, n Notification) {
	if db == nil || db.DB == nil {
		return
	}
	// 5 分钟内同 dedupe 的丢弃，和 plugin.Store.AddNotification 同一口径。
	if n.Dedupe != "" {
		var count int
		cutoff := now.Add(-5 * time.Minute).Format(time.RFC3339)
		_ = db.QueryRow(`SELECT COUNT(*) FROM plugin_notifications WHERE dedupe=? AND created>?`,
			n.Dedupe, cutoff).Scan(&count)
		if count > 0 {
			return
		}
	}
	_, _ = db.Exec(`INSERT INTO plugin_notifications (type, severity, title, body, source, dedupe, created)
		VALUES (?,?,?,?,?,?,?)`, n.Type, n.Severity, n.Title, n.Body, "memguard", n.Dedupe,
		now.Format(time.RFC3339))
}

// Throttled 总量闸踩下 / 松开刹车时说一声。
//
// 必须说：用户看到的是 agent 突然变慢，不说的话那就是「莫名其妙卡住了」——
// 最难查的一类故障。踩下用 warn，松开用 info（那是好消息，不该弹得同样刺眼）。
func Throttled(db *metadb.DB, now time.Time, session, label string, high int64, brake bool) {
	name := session
	if strings.TrimSpace(label) != "" {
		name = label
	}
	if brake {
		add(db, now, Notification{
			Type: "memory", Severity: "warn",
			Title: "已给「" + name + "」减速",
			Body: "机器可用内存不足，这个会话是当前最大的一个，已把它的软限压到 " + human(high) +
				"。它会变慢，但不会被杀；内存缓过来会自动松开。",
			Dedupe: "memthrottle-brake-" + session,
		})
		return
	}
	add(db, now, Notification{
		Type: "memory", Severity: "info",
		Title:  "「" + name + "」已恢复全速",
		Body:   "机器内存缓过来了，之前给它踩的刹车已经松开。",
		Dedupe: "memthrottle-release-" + session,
	})
}

// Compressed 主动压缩回收之后说一声。用 info：这是「趁还来得及，把冷页挪进了
// 交换区」，进程一个字节没少、也没被 throttle —— 不该弹得和减速一样刺眼。
// 但也不能不说：机器紧到需要动手了，人得知道。
func Compressed(db *metadb.DB, now time.Time, session, label string, bytes int64) {
	name := session
	if strings.TrimSpace(label) != "" {
		name = label
	}
	add(db, now, Notification{
		Type: "memory", Severity: "info",
		Title: "已把「" + name + "」的 " + human(bytes) + " 冷内存压进交换区",
		Body: "机器可用内存不足，这个会话是当前最大的一个。压缩回收不影响它跑，" +
			"只是把久未访问的页挪走；如果还不够，下一轮会给它踩软刹车（那时它会变慢）。",
		Dedupe: "memthrottle-reclaim-" + session,
	})
}

// NoSwapRoom 该动手却没落点时提醒人。这条不针对某个会话 —— 是整台机器的事。
//
// 必须说，而且必须说清楚要做什么：这一层到此为止了（开 zram 要 root），
// 不说的话，用户下一次看到的就是「会话又莫名其妙没了」——2026-09-06 22:09
// 那次正是如此，systemd-oomd 按内存压力把整条 scope 端掉，连 shell 带 agent。
func NoSwapRoom(db *metadb.DB, now time.Time, compressed bool) {
	body := "内存回收不出东西了：交换区已经见底，内核扫再多页也腾不出内存，" +
		"再撑一会儿 systemd-oomd 会按压力整条会话端掉（shell 和 agent 一起）。"
	if !compressed {
		body += "这台机器还没开内存压缩（zram/zswap），开上就有地方放：" +
			"sudo bash scripts/dev/install-zram-swap.sh"
	} else {
		body += "压缩已经开着，但也满了 —— 该关掉几个会话，或把 zram 调大。"
	}
	add(db, now, Notification{
		Type: "memory", Severity: "warn",
		Title:  "机器快没内存了，而且压不动",
		Body:   body,
		Dedupe: "memthrottle-noswap",
	})
}

// human 把字节数写成人看的样子。通知正文里 "7.8G" 比 8375186227 有用得多。
func human(n int64) string {
	switch {
	case n <= 0:
		return "—"
	case n >= 1<<30:
		return fmt.Sprintf("%.1fG", float64(n)/float64(1<<30))
	case n >= 1<<20:
		return fmt.Sprintf("%.0fM", float64(n)/float64(1<<20))
	default:
		return fmt.Sprintf("%dK", n>>10)
	}
}
