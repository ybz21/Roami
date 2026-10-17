package memthrottle

import (
	"errors"
	"testing"

	"github.com/ybz21/Roami/internal/memguard"
)

const G = int64(1) << 30

// Plan2 用默认三条线跑 Plan —— 绝大多数用例测的是默认档下的行为。
func Plan2(h Host, samples []Sample) []Decision { return Plan(h, Defaults(), samples) }

// 一台 32G 的机器；hi 是这个会话当前的软限，0 表示 L1 的默认（max×HighRatio）。
//
// Swap 给 2G：意思是「这个会话已经压出去过一轮了」。踩刹车是**压过之后**才轮到的
// 那一步，所以刹车用例的样本都得先满足这个前提；测「先压」那一档的用例自己把
// Swap 清零。
func sample(name string, curGiB int, hi int64) Sample {
	max := 12 * G
	if hi == 0 {
		hi = int64(float64(max) * memguard.HighRatio)
	}
	return Sample{Session: name, PIDs: []int{1}, Cur: int64(curGiB) * G, Swap: 2 * G, High: hi, Max: max}
}

// 机器有 4G 交换区余量、且是压缩的 —— 回收出来的页有地方放，L2 才轮得到动手。
func host(availGiB int) Host {
	return Host{Total: 32 * G, Avail: int64(availGiB) * G, SwapFree: 4 * G, Compressed: true}
}

func TestPlanDoesNothingWhenMemoryIsFine(t *testing.T) {
	// 可用 10/32 = 31%，宽裕
	if got := Plan2(host(10), []Sample{sample("a", 8, 0), sample("b", 6, 0)}); len(got) != 0 {
		t.Fatalf("机器宽裕时不该动手，却得到 %+v", got)
	}
}

func TestPlanBrakesBiggestWhenAvailableIsLow(t *testing.T) {
	// 可用 3/32 = 9.4% < 12%；会话 5+8=13G，占 40% > 35%。
	// big 取 8G：cur×0.85 = 6.8G，还没撞上「必须低于 L1 默认 9G 的九成」那条线，
	// 所以这里测的是 brakeKeep 本身。
	got := Plan2(host(3), []Sample{sample("small", 5, 0), sample("big", 8, 0)})
	if len(got) != 1 {
		t.Fatalf("该踩且只踩一个，得到 %+v", got)
	}
	if got[0].Session != "big" {
		t.Errorf("该踩最大的 big，踩了 %s", got[0].Session)
	}
	if !got[0].Brake {
		t.Error("Brake 该为 true")
	}
	cur := 8 * G // 经变量绕开常量表达式的精确转换要求
	want := int64(float64(cur) * brakeKeep)
	if got[0].High != want {
		t.Errorf("软限 = %d，期望 %d（当前用量的 %.0f%%）", got[0].High, want, brakeKeep*100)
	}
	if got[0].High >= cur {
		t.Error("踩下去的软限必须低于当前用量，否则内核不会开始回收")
	}
}

// 内存是别人吃的时候踩我们自己：既不解决问题，又白白让 agent 变慢。
func TestPlanKeepsHandsOffWhenWeAreNotTheCause(t *testing.T) {
	// 可用 2/32 = 6%，但会话合计只有 5G = 16% < 35%
	if got := Plan2(host(2), []Sample{sample("a", 3, 0), sample("b", 2, 0)}); len(got) != 0 {
		t.Fatalf("主因不是我们时不该动手，却得到 %+v", got)
	}
}

// 滞后区：踩下的判据 12%、松开的判据 20%，中间那段谁也不碰。
// 两条线贴在一起会让会话在 throttle 和放开之间反复横跳。
func TestPlanHysteresisBandTouchesNothing(t *testing.T) {
	braked := sample("big", 14, 4*G)       // 已经踩着
	for _, availGiB := range []int{5, 6} { // 15.6% / 18.75%，都落在 12%–20% 之间
		if got := Plan2(host(availGiB), []Sample{sample("small", 8, 0), braked}); len(got) != 0 {
			t.Errorf("可用 %dG 落在滞后区，不该动手，却得到 %+v", availGiB, got)
		}
	}
}

func TestPlanReleasesWhenMemoryRecovers(t *testing.T) {
	braked := sample("big", 14, 4*G)
	got := Plan2(host(9), []Sample{sample("small", 8, 0), braked}) // 28% > 20%
	if len(got) != 1 {
		t.Fatalf("该松开踩着的那个，得到 %+v", got)
	}
	if got[0].Session != "big" || got[0].Brake {
		t.Errorf("松开该是 Brake=false，得到 %+v", got[0])
	}
	// 松开 = 回到 L1 的默认软限，**不是** 0。真机上踩过这个坑：0 被写成
	// infinity，L1 那道软限跟着没了，会话从此裸奔。
	if want := DefaultHigh(12 * G); got[0].High != want {
		t.Errorf("松开该回到 L1 默认 %d，得到 %d", want, got[0].High)
	}
}

// 松刹车不看占比：卡在踩下状态的会话会一直慢下去，而没人会去手工松它。
func TestPlanReleaseIgnoresShare(t *testing.T) {
	braked := Sample{Session: "tiny", PIDs: []int{1}, Cur: G, High: 2 * G, Max: 12 * G}
	got := Plan2(host(20), []Sample{braked})
	if len(got) != 1 || got[0].High != DefaultHigh(12*G) {
		t.Fatalf("占比再低也该松开，得到 %+v", got)
	}
}

// 已经踩着的不重复踩 —— 否则每轮都按「当前用量×0.85」再压一次，越压越低，
// 最后把会话压死在 brakeFloor 上。
func TestPlanDoesNotRebrakeAlreadyBraked(t *testing.T) {
	got := Plan2(host(3), []Sample{sample("small", 5, 0), sample("big", 14, 4*G)})
	for _, d := range got {
		if d.Session == "big" && d.Brake {
			t.Errorf("big 已经踩着，不该再踩一次: %+v", d)
		}
	}
}

// 小会话踩了腾不出多少，代价却是把它拖垮。
func TestPlanSkipsSessionsBelowFloor(t *testing.T) {
	got := Plan2(host(3), []Sample{
		{Session: "a", PIDs: []int{1}, Cur: 512 << 20, Swap: 2 * G, Max: 12 * G, High: 9 * G},
		{Session: "b", PIDs: []int{2}, Cur: 11 * G, Swap: 2 * G, Max: 12 * G, High: 9 * G},
	})
	if len(got) != 1 || got[0].Session != "b" {
		t.Fatalf("只该踩过得了下限的 b，得到 %+v", got)
	}
}

// 读不到 /proc/meminfo 时不下判断 —— 盲态里踩刹车是最坏的一种猜。
func TestPlanStaysBlindSafe(t *testing.T) {
	for _, h := range []Host{{}, {Total: 32 * G}, {Avail: 3 * G}} {
		if got := Plan2(h, []Sample{sample("big", 20, 0)}); len(got) != 0 {
			t.Errorf("Host=%+v 读不全，不该动手，却得到 %+v", h, got)
		}
	}
}

func TestBrakedRecognisesDefaultHigh(t *testing.T) {
	if sample("a", 8, 0).Braked() {
		t.Error("L1 的默认软限不算踩着刹车")
	}
	if !sample("a", 8, 4*G).Braked() {
		t.Error("被压到默认值之下就是踩着刹车")
	}
	// 没设限的会话（老 scope、护栏装不上的机器）不该被当成踩着
	if (Sample{Session: "a", Cur: 8 * G}).Braked() {
		t.Error("没设限不算踩着刹车")
	}
}

// 一个会话多个 pane：落下一个就算它动了；一个都没落下就不算，
// 免得回头告诉用户「已减速」而实际上什么都没发生。
func TestApplyReportsOnlyWhatLanded(t *testing.T) {
	ds := []Decision{
		{Session: "two-panes", PIDs: []int{1, 2}, High: 4 * G, Brake: true},
		{Session: "all-fail", PIDs: []int{3}, High: 4 * G, Brake: true},
	}
	done := Apply(ds, Effects{SetHigh: func(pid int, _ int64) error {
		if pid == 1 || pid == 3 {
			return errors.New("scope 没了")
		}
		return nil
	}})
	if len(done) != 1 || done[0].Session != "two-panes" {
		t.Fatalf("只该报落下去的那个，得到 %+v", done)
	}
}

// 三条线可配是给不同内存规模的机器用的：128G 上 12% 是 15G 余量，早得没必要；
// 8G 上 12% 只剩 1G，已经太晚。
func TestFromEnvOverridesAndRejectsNonsense(t *testing.T) {
	t.Setenv(EnvAvailLow, "0.30")
	t.Setenv(EnvAvailOK, "0.45")
	t.Setenv(EnvMinShare, "0.10")
	got := FromEnv()
	if got.AvailLow != 0.30 || got.AvailOK != 0.45 || got.MinShare != 0.10 {
		t.Fatalf("环境变量没生效: %+v", got)
	}

	// 「80」而不是「0.8」——写错了就该退回默认，否则机器会被永久踩着刹车
	for _, bad := range []string{"80", "0", "-1", "1", "abc", ""} {
		t.Setenv(EnvAvailLow, bad)
		if FromEnv().AvailLow != availLow {
			t.Errorf("%q 该被拒并退回默认，得到 %v", bad, FromEnv().AvailLow)
		}
	}
}

// 松开线必须严格高于踩下线，否则没有滞后区，会话在两态之间反复横跳。
func TestFromEnvKeepsHysteresisBand(t *testing.T) {
	t.Setenv(EnvAvailLow, "0.40")
	t.Setenv(EnvAvailOK, "0.20") // 配反了
	got := FromEnv()
	if got.AvailOK <= got.AvailLow {
		t.Fatalf("配反了也得留出滞后区，得到 low=%v ok=%v", got.AvailLow, got.AvailOK)
	}
}

// 调宽阈值就该在同一组样本上做出不同决策 —— 端到端演练靠的就是这一点。
func TestPlanHonoursCustomThresholds(t *testing.T) {
	h, ss := host(20), []Sample{sample("big", 14, 0)} // 可用 62.5%，默认档下什么都不做
	if got := Plan(h, Defaults(), ss); len(got) != 0 {
		t.Fatalf("默认档下不该动手，得到 %+v", got)
	}
	loose := Thresholds{AvailLow: 0.70, AvailOK: 0.90, MinShare: 0.10}
	if got := Plan(h, loose, ss); len(got) != 1 || !got[0].Brake {
		t.Fatalf("调宽阈值后该踩下，得到 %+v", got)
	}
}

// 硬顶本来就没设的会话（老 scope、护栏装不上的机器）松开时才是 0：
// 它本来就没有 L1 默认可回。
func TestReleaseWithoutHardCapClearsSoftLimit(t *testing.T) {
	if DefaultHigh(0) != 0 {
		t.Error("没有硬顶就没有默认软限可回")
	}
}

// 会话用量贴近硬顶时，cur×0.85 和 L1 默认只差几个页面 —— 那一脚等于没踩，
// 而且下一轮 Braked() 认不出来，于是每轮重踩。真机演练里踩出过 4096 字节的差。
func TestBrakeAlwaysLandsBelowDefaultHigh(t *testing.T) {
	max := 12 * G
	for _, curGiB := range []int{9, 10, 11} { // 都在 0.75×max 之上
		s := Sample{Session: "x", PIDs: []int{1}, Cur: int64(curGiB) * G, Swap: 2 * G,
			High: DefaultHigh(max), Max: max}
		got := Plan(host(3), Thresholds{AvailLow: 0.20, AvailOK: 0.40, MinShare: 0.01}, []Sample{s})
		if len(got) != 1 {
			t.Fatalf("cur=%dG 该踩，得到 %+v", curGiB, got)
		}
		after := Sample{Session: "x", PIDs: []int{1}, Cur: s.Cur, High: got[0].High, Max: max}
		if !after.Braked() {
			t.Errorf("cur=%dG 踩成 %d，但 Braked() 认不出来（L1 默认 %d）",
				curGiB, got[0].High, DefaultHigh(max))
		}
	}
}

// 先压后踩：没压过的会话，第一轮只做主动压缩回收，软限一动不动。
//
// 这是 2026-09-06 22:09 那次事故改出来的一档。在那之前 L2 直接踩软限，
// 而软限不回收内存 —— 它只是让内核在每次分配上做直接回收，回收不出来就干转，
// PSI 冲高，systemd-oomd 把整条 scope（shell 带 agent 20 个进程）一起端掉。
func TestPlanCompressesBeforeBraking(t *testing.T) {
	fresh := sample("big", 8, 0)
	fresh.Swap = 0 // 还没压过
	got := Plan2(host(3), []Sample{sample("small", 5, 0), fresh})
	if len(got) != 1 || got[0].Session != "big" {
		t.Fatalf("该动最大的 big，得到 %+v", got)
	}
	if got[0].Brake || got[0].High != 0 {
		t.Errorf("第一轮只压不踩，软限该一动不动，得到 %+v", got[0])
	}
	cur := 8 * G // 经变量绕开常量表达式的精确转换要求
	want := int64(float64(cur) * reclaimShare)
	if want > reclaimCap {
		want = reclaimCap
	}
	if got[0].Reclaim != want {
		t.Errorf("该压 %d，得到 %d", want, got[0].Reclaim)
	}
}

// 压过一轮还不够，下一轮才踩刹车。判据从内核读（memory.swap.current），
// 不在进程里记 —— CLI 每次调用都是一个新进程，记在内存里的状态活不过这一轮。
func TestPlanBrakesAfterCompressionDidNotHelp(t *testing.T) {
	got := Plan2(host(3), []Sample{sample("small", 5, 0), sample("big", 8, 0)}) // sample() 自带 Swap=2G
	if len(got) != 1 || !got[0].Brake {
		t.Fatalf("压过之后该踩刹车，得到 %+v", got)
	}
	if got[0].Reclaim != 0 {
		t.Errorf("踩刹车这一轮不该再压一次: %+v", got[0])
	}
}

// 交换区见底 = 回收出来的页没地方放。这时**什么都不做**是有意的：
// 踩下去只是干转，而单会话失控仍有 L1 的硬顶兜着（撞顶只杀它自己）。
func TestPlanKeepsHandsOffWhenNowhereToPutPages(t *testing.T) {
	h := host(3)
	h.SwapFree, h.Compressed = 8<<20, false // 8M，等于没有
	if got := Plan2(h, []Sample{sample("small", 5, 0), sample("big", 8, 0)}); len(got) != 0 {
		t.Fatalf("没落点时不该动手，却得到 %+v", got)
	}
}

// 动不了就得让人知道 —— 这一层自己解决不了（开 zram 要 root）。
func TestStalledFiresOnlyWhenWeWouldHaveActed(t *testing.T) {
	full := host(3)
	full.SwapFree, full.Compressed = 8<<20, false
	ours := []Sample{sample("small", 5, 0), sample("big", 8, 0)} // 合计 40% > 35%
	if !Stalled(full, Defaults(), ours) {
		t.Error("过线 + 主因是我们 + 没落点：该提醒")
	}
	if Stalled(host(3), Defaults(), ours) {
		t.Error("交换区还有余量，动得了，不该提醒")
	}
	if Stalled(full, Defaults(), []Sample{sample("a", 3, 0), sample("b", 2, 0)}) {
		t.Error("内存不是我们吃的，不该提醒")
	}
	if Stalled(full, Defaults(), nil) {
		t.Error("没有会话可动，不该提醒")
	}
	// 机器宽裕的时候压根不该冒出这条
	loose := host(20)
	loose.SwapFree, loose.Compressed = 8<<20, false
	if Stalled(loose, Defaults(), ours) {
		t.Error("机器宽裕时不该提醒")
	}
}

// 别开一张交换区兑不了的空头支票：要得比剩余还多，内核只会尽力而为，
// 而下一轮 top.Swap 又达不到目标，于是每一轮都重压一次。
func TestReclaimTargetNeverExceedsRoomOrCap(t *testing.T) {
	if got := reclaimTarget(40*G, 100*G); got != reclaimCap {
		t.Errorf("单轮该封顶在 %d，得到 %d", reclaimCap, got)
	}
	if got := reclaimTarget(8*G, 200<<20); got != 200<<20 {
		t.Errorf("该被交换区余量卡到 200M，得到 %d", got)
	}
	if got := reclaimTarget(200<<20, 4*G); got != 0 {
		t.Errorf("小到不值得压就别压，得到 %d", got)
	}
}

// 一个会话多个 pane：压也是挨个 pane 压，落下一个就算这个会话动了。
func TestApplyRoutesReclaimDecisions(t *testing.T) {
	var got []int64
	done := Apply([]Decision{{Session: "x", PIDs: []int{7}, Reclaim: 256 << 20}}, Effects{
		SetHigh: func(int, int64) error { t.Error("这一轮不该动软限"); return nil },
		Reclaim: func(_ int, n int64) error { got = append(got, n); return nil },
	})
	if len(done) != 1 || len(got) != 1 || got[0] != 256<<20 {
		t.Fatalf("该只调压缩回收一次，得到 done=%+v calls=%v", done, got)
	}
}
