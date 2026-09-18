package keepalive

import (
	"fmt"
	"os"
	"strconv"
	"time"

	"ttmux-cli-go/pkg/plugin/sdk"
)

// tickInterval 是常驻循环的巡检周期,也就是「安静了多久」这个判断的精度。
const tickInterval = 30 * time.Second

// staleAfterSec 超过这么久没巡检,面板就该把横幅转黄说「守护循环没在跑」。
// 取 4 轮:偶尔一轮卡在 tmux 上不该吓唬人,连着四轮不动就是真出事了。
const staleAfterSec = int64(tickInterval/time.Second) * 4

// tickCmd 巡检一轮:该催的催、该停手的停手,并顺手清掉已经没了的会话。
// 幂等,可由外部 timer 驱动(同 roam.cron 的 tick)。
func tickCmd(ctx *sdk.Ctx, args map[string]string) (any, error) {
	return tickOnce(ctx)
}

// serve 常驻守护循环。由 plugind 在 `_ttmux-keepalive` 会话里拉起,掉了重拉
// (见 internal/plugin/daemon.go)。守护表空了就自己退出——没活干还占着一个
// 会话和一个进程,是白占。
func serve(ctx *sdk.Ctx, args map[string]string) (any, error) {
	fmt.Fprintf(os.Stderr, "[%s] 会话守护循环启动,每 %s 看一眼\n", nowStr(), tickInterval)
	ctx.Logf("guard loop started (tick=%s)", tickInterval)
	rounds := 0
	for {
		res, err := tickOnce(ctx)
		if err != nil {
			fmt.Fprintf(os.Stderr, "[%s] 巡检出错: %v\n", nowStr(), err)
		} else if m, ok := res.(map[string]any); ok {
			if n, _ := m["guarded"].(int); n == 0 {
				fmt.Fprintf(os.Stderr, "[%s] 已经没有要守护的会话了,循环退出\n", nowStr())
				ctx.Logf("no guards left; loop exits")
				return map[string]any{"rounds": rounds, "exit": "no-guards"}, nil
			}
			if sent, _ := m["sent"].([]string); len(sent) > 0 {
				fmt.Fprintf(os.Stderr, "[%s] 催了 %d 个会话\n", nowStr(), len(sent))
			}
		}
		rounds++
		time.Sleep(tickInterval)
	}
}

// tickOnce 是巡检的全部。判断逻辑在 Step(纯函数),这里只负责跟宿主打交道:
// 问会话、抓屏幕、发消息、落账。
func tickOnce(ctx *sdk.Ctx) (any, error) {
	guards, err := loadGuards(ctx)
	if err != nil {
		return nil, err
	}
	_ = ctx.StorageSet(tickKey, strconv.FormatInt(time.Now().Unix(), 10))
	if len(guards) == 0 {
		return map[string]any{"guarded": 0, "sent": []string{}}, nil
	}
	st, err := loadSettings(ctx)
	if err != nil {
		return nil, err
	}
	sessions, err := ctx.SessionListAll()
	if err != nil {
		return nil, err
	}
	// tmux 盲态(一个会话都问不到)时什么都不做。把「看不见」当成「全都没了」,
	// 一轮就能把整张守护表清空——而 tmux 只是重启了一下。
	if len(sessions) == 0 {
		return map[string]any{"guarded": CountEnabled(guards), "sent": []string{}, "blind": true}, nil
	}
	live := make(map[string]sdk.AllSession, len(sessions))
	for _, s := range sessions {
		live[s.Session] = s
	}

	rules := loadRules(ctx)
	now := time.Now().Unix()
	kept := make([]Guard, 0, len(guards))
	sent, stopped, dropped := []string{}, []string{}, []string{}
	for _, g := range guards {
		s, alive := live[g.Session]
		if !alive {
			// 会话 id 由时间戳派生、永不复用,所以「不在了」就是永远不在了:
			// 这条守护留着只会变成一行没人看得懂的僵尸。记录里还有它。
			dropped = append(dropped, g.Session)
			continue
		}
		g.Label = s.Label

		p := Probe{Alive: true}
		var screen string
		if g.Enabled {
			if out, cerr := ctx.SessionCapture(g.Session, CaptureLines); cerr == nil {
				screen, p.Hash = out, ScreenHash(out)
			}
		}
		d := Step(g, p, st, now)

		switch {
		case d.Stop:
			stopped = append(stopped, g.Session)
			announceStop(ctx, d.Guard, st)
		case d.Send:
			text, rule := PickPrompt(rules, screen, d.Nth, d.Guard.Effective(st).Prompt)
			rec := Send{
				At: now, Session: g.Session, Label: g.Label, Prompt: text,
				Trigger: "watch", Rule: rule, Nth: d.Nth, QuietSec: d.QuietSec,
			}
			if serr := ctx.SessionSend(g.Session, text); serr != nil {
				// 发不出去(会话刚好在这一刻没了之类)不该让整轮巡检翻车:
				// 记一笔,这条守护照常留着,下一轮再说。
				rec.Error = serr.Error()
				fmt.Fprintf(os.Stderr, "[%s] 催 %s 失败: %v\n", nowStr(), g.Session, serr)
			} else {
				sent = append(sent, g.Session)
				ctx.Logf("催了 %s(安静 %d 分钟,第 %d 次):%s", g.Label, d.QuietSec/60, d.Nth, text)
			}
			record(ctx, rec)
		}
		kept = append(kept, d.Guard)
	}
	if err := saveGuards(ctx, kept); err != nil {
		return nil, err
	}
	return map[string]any{
		"guarded": CountEnabled(kept), "sent": sent, "stopped": stopped, "dropped": dropped,
	}, nil
}

// announceStop 停手必须吭声:静悄悄停掉的守护,和从来没开过是一回事。
func announceStop(ctx *sdk.Ctx, g Guard, st Settings) {
	eff := g.Effective(st)
	ctx.Logf("会话 %s 连催 %d 次没反应,已自动停手", g.Label, eff.MaxQuiet)
	record(ctx, Send{
		At: g.StoppedAt, Session: g.Session, Label: g.Label, Prompt: eff.Prompt,
		Trigger: "watch", Rule: -1, Nth: g.Sends, Stopped: true,
	})
	_ = ctx.NotificationPublish(sdk.Notification{
		Type:     "keepalive.stopped",
		Severity: "warning",
		Title:    fmt.Sprintf("会话「%s」连催 %d 次没反应，已停手", g.Label, eff.MaxQuiet),
		Body: fmt.Sprintf("最后发的是「%s」。会话 %s 的屏幕一直没变——去看一眼它是不是已经退回 shell 了。\n"+
			"想再试的话，在插件页「会话守护」里把它的开关重新打开。", eff.Prompt, g.Session),
		// 同一个会话同一轮停手只报一次;重新打开再停手时 Sends 变了,会是新的一条。
		DedupeKey: fmt.Sprintf("keepalive.stopped.%s.%d", g.Session, g.Sends),
	})
}

func nowStr() string { return time.Now().Format("15:04:05") }
