// 会话跑进 worktree 之后，台账里的 home_dir 还停在建会话那一刻的目录（钉死不随 cwd 漂移，
// 见 worktree/sessionhome.go 的 pin）。树上按 pane 实际所在的 worktree 把它挂在任务下，
// 重启后却按台账在主仓库重开——用户看到的就是「任务全成了待收尾，会话掉进散会话」。
//
// 这里把两边对齐：pane 落在 linked worktree 里，就把台账（CLI 的 sessions 表）和运行时归属
// 一起改钉到那个 worktree。只认 linked worktree、只在变化时写：主仓库不改（cd 出去逛一圈
// 不该把归属抹掉），同一个值不重复写。
package api

import (
	"context"
	"log"
	"sync"
	"time"

	"github.com/ybz21/Roami/backend/ttmux"
	"github.com/ybz21/Roami/backend/worktree"
)

// AgentLinkLoop 后台每 15s 扫一次进程树：对「会话 ↔ claude 对话 id」的账、把跑进 worktree 的会话
// 在台账里改钉过去。**不挂在 /projects 请求上**：没开浏览器时起的 claude 也得认得，重启后也得马上补账。
func (a *API) AgentLinkLoop() {
	t := time.NewTicker(15 * time.Second)
	defer t.Stop()
	for {
		a.agentLink.reconcile(runningAgentProcs(), a.linkAgentSession)
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		a.syncSessionHomes(a.WT.Annotations(ctx))
		cancel()
		<-t.C
	}
}

var homeSynced sync.Map // 会话名 → 上次已同步的 worktree 路径

func (a *API) syncSessionHomes(ann map[string]*worktree.Annotation) {
	for name, an := range ann {
		if an == nil || an.Primary == nil || !an.Primary.Linked || an.Primary.Worktree == "" {
			continue
		}
		dir := an.Primary.Worktree
		if v, ok := homeSynced.Load(name); ok && v == dir {
			continue
		}
		homeSynced.Store(name, dir)
		if a.WT.SessionHome(name) == dir {
			continue
		}
		a.WT.BindSessionHome(name, dir)
		if out, err := a.TT.Run("db", "set-home", name, dir); err != nil {
			log.Printf("同步会话归属失败 %s → %s: %s", name, dir, ttmux.StripANSI(out))
		}
	}
}
