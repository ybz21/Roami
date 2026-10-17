package memguard

import (
	"os"
	"testing"
)

// 真机演练：拿测试进程自己的 scope 跑一次主动压缩回收。
//
// 默认跳过 —— 它真的会去动 cgroup，而 CI 上没有 tmux 的 scope、也未必有交换区。
// 但这一档的验收只能在真机上做：单测里 Plan 决定「压多少」，压得动压不动是内核的事。
//
//	ROAM_RECLAIM_LIVE=1 go test ./internal/memguard/ -run TestLiveReclaim -v
//
// 本机实测（30G / 8G swap）：要 64 M，anon 掉了 62 M，memory.swap.current 涨了 38 M，
// 耗时 60 ms —— 会话列表刷新一轮的开销扛得住，而进程一个字节没被 throttle。
func TestLiveReclaim(t *testing.T) {
	if os.Getenv("ROAM_RECLAIM_LIVE") == "" {
		t.Skip("真机演练，需 ROAM_RECLAIM_LIVE=1")
	}
	pid := os.Getpid()
	if cgroupDir(pid) == "" {
		t.Skip("这个进程不在 cgroup v2 里")
	}
	swapBefore, _ := SwapOf(pid)
	anonBefore, _, _ := Current(pid)
	t.Logf("压之前: anon=%d swap.current=%d 交换区余量=%d", anonBefore, swapBefore, SwapFree())

	err := Reclaim(pid, 64<<20)
	swapAfter, _ := SwapOf(pid)
	anonAfter, _, _ := Current(pid)
	t.Logf("压之后: anon=%d(%+d) swap.current=%d(%+d) err=%v",
		anonAfter, anonAfter-anonBefore, swapAfter, swapAfter-swapBefore, err)

	// 交换区满的机器上压不动是**正常结果**，而且必须报成错——那正是这次要修的东西：
	// 报成功而实际一页没动，用户就以为已经替他压过了。
	if err == nil && swapAfter <= swapBefore {
		t.Error("报了成功，交换区却一页也没接住")
	}
}
