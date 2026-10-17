package memguard

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestFromEnvDefaults(t *testing.T) {
	t.Setenv("ROAM_SESSION_MEM_MAX", "")
	t.Setenv("ROAM_SESSION_MEM_HIGH", "")
	t.Setenv("ROAM_SESSION_MEM_SWAP", "")
	l := FromEnv()
	if l.Off() {
		t.Fatal("默认额度不该是 Off")
	}
	max, ok := parseBytes(l.Max)
	if !ok {
		t.Fatalf("默认 Max 解析不出: %q", l.Max)
	}
	// 下限保证小内存机器也有个说得过去的额度；上限避免大内存机器给到几十 G 等于没设。
	if max < defaultFloor || max > defaultCeil {
		t.Fatalf("默认 Max = %d，超出 [%d,%d]", max, defaultFloor, defaultCeil)
	}
	// 本仓库 npm run build 实测峰值 7.4G。默认额度低于它就会误伤正常构建，
	// 而那种死法很隐蔽（V8 自己 abort，cgroup 的 oom_kill 计数是 0）。
	if total := totalMemory(); total >= 20<<30 && max < 8<<30 {
		t.Fatalf("20G+ 的机器默认只给 %d 字节，连一次前端构建都跑不完", max)
	}
	high, ok := parseBytes(l.High)
	if !ok || high >= max {
		t.Fatalf("软限 %q 必须严格低于硬顶 %q，否则没有 throttle 的窗口", l.High, l.Max)
	}
	if swap, ok := parseBytes(l.Swap); !ok || swap > max {
		t.Fatalf("swap 额度 %q 不该超过内存额度 %q", l.Swap, l.Max)
	}
}

func TestDefaultMaxScalesWithRAM(t *testing.T) {
	// 读不到 /proc/meminfo 的环境（非 Linux、受限容器）也必须给出一个能用的值。
	if _, ok := parseBytes(DefaultMax()); !ok {
		t.Fatalf("DefaultMax() 返回了解析不出的值: %q", DefaultMax())
	}
}

// 「显式不限」是给「我就是要跑个吃 20G 的东西」留的门，几种写法都得认。
func TestFromEnvOff(t *testing.T) {
	for _, v := range []string{"0", "off", "OFF", "none", "unlimited"} {
		t.Setenv("ROAM_SESSION_MEM_MAX", v)
		if l := FromEnv(); !l.Off() {
			t.Fatalf("ROAM_SESSION_MEM_MAX=%q 应当关闭护栏，得到 %+v", v, l)
		}
	}
}

func TestFromEnvOverride(t *testing.T) {
	t.Setenv("ROAM_SESSION_MEM_MAX", "4G")
	t.Setenv("ROAM_SESSION_MEM_HIGH", "3500M")
	t.Setenv("ROAM_SESSION_MEM_SWAP", "1G")
	l := FromEnv()
	if l.Max != "4G" || l.High != "3500M" || l.Swap != "1G" {
		t.Fatalf("显式设的值被改写了: %+v", l)
	}
}

func TestScaleBytes(t *testing.T) {
	G := int64(1) << 30
	cases := []struct {
		in   string
		want int64 // 字节；-1 = 期望空串
	}{
		{"8G", 6 * G},
		{"4G", 3 * G},
		// 不整除的额度是这个函数最容易出错的地方：按单位做整数除法会把
		// 6G 的 75% 截成 4G，凭空少半个 G，而 8G 正好整除时看不出来。
		{"6G", 6 * G * 3 / 4},
		{"2000M", 2000 * (1 << 20) * 3 / 4},
		{"1G", G * 3 / 4},
		{"8GiB", 6 * G},
		{"", -1},
		{"G", -1},   // 认不出就返回空，宁可不设软限也别设错
		{"abc", -1}, //
	}
	for _, c := range cases {
		got := scaleBytes(c.in, highRatio)
		if c.want < 0 {
			if got != "" {
				t.Errorf("scaleBytes(%q) = %q, want empty", c.in, got)
			}
			continue
		}
		n, ok := parseBytes(got)
		if !ok || n != c.want {
			t.Errorf("scaleBytes(%q) = %q (%d), want %d", c.in, got, n, c.want)
		}
	}
}

// 软限必须严格低于硬顶，否则先撞硬顶、根本没有 throttle 的窗口。
// 各种额度写法都要成立，不只是正好整除的那些。
func TestHighAlwaysBelowMax(t *testing.T) {
	for _, max := range []string{"8G", "6G", "12G", "3500M", "1G", "13304680448"} {
		l := From(max, "", "")
		m, ok1 := parseBytes(l.Max)
		h, ok2 := parseBytes(l.High)
		if !ok1 || !ok2 {
			t.Fatalf("max=%q 解析失败: %+v", max, l)
		}
		if h >= m {
			t.Errorf("max=%q → High=%d 不低于 Max=%d", max, h, m)
		}
	}
}

// ScopeOf 读的是真 /proc。跑在 systemd 用户会话里就该拿到 .scope，
// 其他环境（容器、CI）拿到空串——两种都是正确行为，不该 panic 或返回垃圾。
func TestScopeOfSelf(t *testing.T) {
	unit := ScopeOf(os.Getpid())
	if unit != "" && !strings.HasSuffix(unit, ".scope") {
		t.Fatalf("ScopeOf 返回了不像 scope 的东西: %q", unit)
	}
	if unit != "" && strings.ContainsAny(unit, "/ \t\n") {
		t.Fatalf("scope 单元名不该含路径或空白: %q", unit)
	}
}

// cgroup v1 的 /proc/<pid>/cgroup 是多行。照 v2 的写法解析会得出登录会话的
// scope —— 一个看着很像、其实是别人家的路径，给它设上限就限制了该用户所有进程。
// 实测 jetson（Ubuntu 20.04）就是 v1，所以这条不是假想。
func TestCgroupPathRejectsV1(t *testing.T) {
	dir := t.TempDir()
	v1 := `12:pids:/user.slice/user-1000.slice/session-4195.scope
11:memory:/user.slice
0::/user.slice/user-1000.slice/session-4195.scope`
	if err := os.WriteFile(filepath.Join(dir, "cgroup"), []byte(v1), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := parseCgroupFile(v1); got != "" {
		t.Fatalf("v1 多行格式应当被拒，得到 %q", got)
	}
	if got := parseCgroupFile("0::/user.slice/tmux-spawn-abc.scope"); got != "/user.slice/tmux-spawn-abc.scope" {
		t.Fatalf("v2 单行解析错了: %q", got)
	}
	if got := parseCgroupFile("1:name=systemd:/foo"); got != "" {
		t.Fatalf("没有 0:: 前缀的应当被拒，得到 %q", got)
	}
}

func TestScopeOfMissingPID(t *testing.T) {
	if got := ScopeOf(-1); got != "" {
		t.Fatalf("不存在的 pid 应当返回空串，得到 %q", got)
	}
}

// 护栏装不上时必须静默降级——绝不能因此中断建会话。
func TestApplyOffIsNoop(t *testing.T) {
	if err := Apply(os.Getpid(), Limits{}); err != nil {
		t.Fatalf("Off 额度应当直接返回 nil，得到 %v", err)
	}
	if err := Apply(-1, Limits{Max: "1G"}); err != nil {
		t.Fatalf("拿不到 scope 应当静默跳过，得到 %v", err)
	}
}

func TestCurrentMissingPID(t *testing.T) {
	if _, _, ok := Current(-1); ok {
		t.Fatal("不存在的 pid 不该报告成功")
	}
	if n := OOMKilled(-1); n != 0 {
		t.Fatalf("不存在的 pid 的 oom_kill 应当是 0，得到 %d", n)
	}
}
