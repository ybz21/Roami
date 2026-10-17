// Package memguard 给会话套一层内存天花板，让失控的 agent 只杀死自己。
//
// 2026-08-22 21:51，一个跑在 Roami 会话里的 Claude Code 进程涨到 15.5 GB，
// 把整台 30 GB 的机器打爆（global_oom，内核在全机范围选 victim，桌面整个僵住）。
// 后端自己当时只有 38 MB——问题不是哪里漏了，是**编排器对被编排的进程没有任何约束**。
//
// 隔离边界其实早就在：本机 tmux 带 systemd 支持，每个 pane 自动落进一个
// tmux-spawn-<uuid>.scope；memory 控制器也已委派到用户切片。所以只要在会话建好后
// 给那个 scope 设一次 MemoryMax，撞顶时 cgroup OOM 只在该 scope 内选 victim——
// 被杀的是失控的 agent，shell 和会话都还活着。不需要 root，不改进程树。
//
// 见 docs/design/reliability/memory-guard.html。
package memguard

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

// 默认额度按**物理内存的比例**算，不写死一个数。
//
// 一开始写死 8G，理由是 agent 健康态实测 180–600 MB、8G 是 20× 余量。
// 但同一个会话里也会跑构建：本仓库 `npm run build` 实测峰值 **7.4 GB**
// （monaco 4.3 MB + mermaid 3.4 MB 那几个大 chunk），8G 当场把它压死——
// 而且死法很隐蔽：`memory.events` 里 oom_kill=0，是 Node 读到 cgroup 限额后
// 自己把 V8 堆设小、然后在 V8 层 abort，看起来完全不像内存上限干的。
//
// 40% 在这台 30 GB 机器上是 12 GB：拦得住 15.5 GB 那种失控，放得过 7.4 GB 的构建。
// 上下限兜住极端机型：小内存机器至少给 4G，大内存机器不必给到几十 G。
const (
	defaultRatio = 0.40
	defaultFloor = 4 << 30  // 4G
	defaultCeil  = 24 << 30 // 24G
	// swapRatio swap 额度占内存额度的比例。给一点缓冲，但别让它把 swap 吃穿。
	swapRatio = 0.25
	// highRatio 软限占硬限的比例。先到软限时内核激进回收并 throttle，
	// 进程变慢但不死，给看门狗留出反应时间。
	highRatio = 0.75
)

// Limits 是一个会话的内存额度。空串 = 不设那一项。
type Limits struct {
	Max  string // MemoryMax，硬顶，撞到就 cgroup OOM
	High string // MemoryHigh，软限，撞到只回收+throttle
	Swap string // MemorySwapMax，别让它把 swap 也吃穿
}

// Off 表示显式不限（用户在设置里关掉，或环境变量设成 0/off）。
func (l Limits) Off() bool { return l.Max == "" }

// 配置项名。设置页写进 ttmux 的全局 env 文件，环境变量可临时覆盖。
const (
	EnvMax  = "ROAM_SESSION_MEM_MAX"
	EnvHigh = "ROAM_SESSION_MEM_HIGH"
	EnvSwap = "ROAM_SESSION_MEM_SWAP"
)

// FromEnv 读全局默认额度（只看进程环境变量）。
// 会话路径走 From()——那里还会读设置页写的 env 文件。
func FromEnv() Limits {
	return From(os.Getenv(EnvMax), os.Getenv(EnvHigh), os.Getenv(EnvSwap))
}

// From 由三个配置值算出额度。空值走默认，high/swap 空则按比例从 max 推。
//
// max = 0 / off / none / unlimited 表示不限——给「我就是要跑个吃 20G 的东西」
// 留门，但那得是明确的选择，不能是默认。
func From(max, high, swap string) Limits {
	max = strings.TrimSpace(max)
	if max == "" {
		max = DefaultMax()
	}
	switch strings.ToLower(max) {
	case "0", "off", "none", "unlimited":
		return Limits{}
	}
	swap = strings.TrimSpace(swap)
	if swap == "" {
		swap = scaleBytes(max, swapRatio)
	}
	high = strings.TrimSpace(high)
	if high == "" {
		high = scaleBytes(max, highRatio)
	}
	return Limits{Max: max, High: high, Swap: swap}
}

// DefaultMax 本机的默认单会话上限（字节数的十进制串，systemd 认）。
// 读不出物理内存就退回下限——宁可管得松些，也不能因为读不到就不设防。
func DefaultMax() string {
	total := totalMemory()
	if total <= 0 {
		return strconv.FormatInt(defaultFloor, 10)
	}
	n := int64(float64(total) * defaultRatio)
	if n < defaultFloor {
		n = defaultFloor
	}
	if n > defaultCeil {
		n = defaultCeil
	}
	return strconv.FormatInt(n, 10)
}

// totalMemory 物理内存字节数（读不到返回 0）。
func totalMemory() int64 { return meminfoBytes("MemTotal:") }

// TotalMemory 本机物理内存（字节，读不到 0）。总量闸拿它当分母。
func TotalMemory() int64 { return totalMemory() }

// AvailableMemory 内核估的**还能拿去用**的内存（字节，读不到 0）。
//
// 判「机器要不要卡死了」只能用它，不能用 MemFree：page cache 算在 free 之外，
// 而它是随时可回收的 —— 拿 MemFree 判会在一台内存充裕、只是缓存占满的机器上
// 一直误报。MemAvailable 是内核替我们算过回收余量之后的数。
func AvailableMemory() int64 { return meminfoBytes("MemAvailable:") }

// meminfoBytes 取 /proc/meminfo 里某一行的字节数（该行以 kB 计）。
func meminfoBytes(key string) int64 {
	b, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return 0
	}
	for _, line := range strings.Split(string(b), "\n") {
		if !strings.HasPrefix(line, key) {
			continue
		}
		f := strings.Fields(line)
		if len(f) < 2 {
			return 0
		}
		kb, err := strconv.ParseInt(f[1], 10, 64)
		if err != nil {
			return 0
		}
		return kb << 10
	}
	return 0
}

// available 缓存「这台机器能不能设上限」。判定要便宜：护栏装不上应当降级成
// 「和以前一样」，绝不能变成「开不出会话」。
var (
	availOnce sync.Once
	availOK   bool
)

func available() bool {
	availOnce.Do(func() {
		// cgroup v2 统一层级：v1 的控制器分散在多个挂载点上，本包的读写路径全按
		// v2 的单一层级来，没有它一切免谈。
		if _, err := os.Stat("/sys/fs/cgroup/cgroup.controllers"); err != nil {
			return
		}
		if _, err := exec.LookPath("systemctl"); err != nil {
			return
		}
		if os.Getenv("XDG_RUNTIME_DIR") == "" {
			return
		}
		// memory 控制器必须已经委派到用户切片，否则 set-property 会失败
		b, err := os.ReadFile("/sys/fs/cgroup/user.slice/user-" +
			strconv.Itoa(os.Getuid()) + ".slice/user@" +
			strconv.Itoa(os.Getuid()) + ".service/cgroup.controllers")
		availOK = err == nil && strings.Contains(string(b), "memory")
	})
	return availOK
}

// cgroupPath 读进程的 cgroup v2 路径（形如 /user.slice/.../tmux-spawn-<uuid>.scope）。
//
// **只认 v2**，格式是唯一的一行 `0::<path>`。v1 的 /proc/<pid>/cgroup 是多行
// `<n>:<controller>:<path>`，照 v2 的写法去截最后一个冒号，会解析出**登录会话**
// 的 scope（session-4195.scope）——那不是这个 pane 的，给它设上限等于限制该用户
// 的所有进程。实测 jetson（Ubuntu 20.04 / cgroup v1）就长这样。
//
// available() 那道也拦得住（v1 上读不到委派文件），但这种「解析出一个看着很像、
// 其实是别人家的路径」的错法后果太重，不该只靠一道。
func cgroupPath(pid int) string {
	b, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/cgroup")
	if err != nil {
		return ""
	}
	return parseCgroupFile(string(b))
}

// parseCgroupFile 从 /proc/<pid>/cgroup 的内容里取出 v2 路径（认不出返回空串）。
func parseCgroupFile(content string) string {
	lines := strings.Split(strings.TrimSpace(content), "\n")
	if len(lines) != 1 {
		return "" // 多行 = cgroup v1，本包不支持
	}
	path, ok := strings.CutPrefix(strings.TrimSpace(lines[0]), "0::")
	if !ok {
		return ""
	}
	return strings.TrimSpace(path)
}

// cgroupDir 该进程 cgroup 在 sysfs 里的目录（拿不到返回空串）。
func cgroupDir(pid int) string {
	p := cgroupPath(pid)
	if p == "" {
		return ""
	}
	return "/sys/fs/cgroup" + p
}

// ScopeOf 返回一个进程所属的 systemd scope 单元名（拿不到返回空串）。
// tmux 给每个 pane 建一个 tmux-spawn-<uuid>.scope，pane 里的所有后代都在里面。
func ScopeOf(pid int) string {
	p := cgroupPath(pid)
	if p == "" {
		return ""
	}
	unit := filepath.Base(p)
	if !strings.HasSuffix(unit, ".scope") {
		return "" // 不在 scope 里（容器、非 systemd 环境）就别硬套
	}
	return unit
}

// 设上限要重试，而且**只能以回读的结果为准**。
//
// tmux 建 pane 和 systemd 注册那个 scope 是异步的，而且两边不同步：内核层面的
// cgroup 目录先建好（此刻 /proc/<pid>/cgroup 已经指向新 scope，ScopeOf 拿得到名字），
// systemd 那边的 unit 却还没注册完。这个窗口里 `systemctl set-property` 会
// **静默成功**——exit 0、无输出，但属性落在一个 systemd 还不认识的名字上，
// unit 真正创建时并不继承。实测表现就是「同一段代码，四次里成两次」。
//
// 所以判据不是「命令返回 0」，也不是「拿到 scope 名了」，而是
// **memory.max 真的变成了我们要的值**。
const (
	applyWait  = 2 * time.Second
	applyRetry = 25 * time.Millisecond
)

// Apply 给一个 pane 所在的 scope 设上限，并确认真的生效。
//
// 装不上就静默跳过：返回 error 只为让调用方能记一行日志，绝不该因此中断建会话。
// 重复调用安全（set-property 幂等），所以除了建会话，attach 时也会再补一次——
// split-window / new-window 开出来的新 pane 有自己的 scope，只在建会话时设一次会漏掉。
func Apply(pid int, l Limits) error {
	if l.Off() || !available() {
		return nil
	}
	want, ok := parseBytes(l.Max)
	if !ok {
		return fmt.Errorf("memguard: 认不出的额度 %q", l.Max)
	}
	deadline := time.Now().Add(applyWait)
	var lastErr error
	for {
		// 进程没了就没什么好设的：直接走人，别干等满 applyWait。
		// 会话建完立刻被 kill、或 pid 压根不存在，都会走到这里。
		if cgroupPath(pid) == "" {
			return nil
		}
		if unit := ScopeOf(pid); unit != "" {
			if err := setProperty(unit, l); err != nil {
				lastErr = err
			} else if got, ok := currentMax(pid); ok && got == want {
				return nil // 回读确认：这一次是真的设上了
			}
		}
		if time.Now().After(deadline) {
			if lastErr != nil {
				return lastErr
			}
			return fmt.Errorf("memguard: %s 上限未在 %v 内生效", l.Max, applyWait)
		}
		time.Sleep(applyRetry)
	}
}

func setProperty(unit string, l Limits) error {
	args := []string{"--user", "set-property", unit, "MemoryMax=" + l.Max}
	if l.High != "" {
		args = append(args, "MemoryHigh="+l.High)
	}
	if l.Swap != "" {
		args = append(args, "MemorySwapMax="+l.Swap)
	}
	return exec.Command("systemctl", args...).Run()
}

// Limit 这个 pane 所在 cgroup 的内存上限（字节）。0 = 未设限（cgroup 里写着 "max"）。
// 会话列表的内存条要拿它当分母，看门狗要拿它算百分比。
func Limit(pid int) int64 {
	n, _ := currentMax(pid)
	return n
}

// currentMax 回读这个 pane 所在 cgroup 的 memory.max（"max" = 未设限）。
func currentMax(pid int) (int64, bool) { return currentLimit(pid, "memory.max") }

// HighRatio 是软限相对硬顶的默认比例。总量闸靠它认出「这个会话是不是被踩着刹车」——
// 软限明显低于 max×HighRatio，就是有人单独压过它。
const HighRatio = highRatio

// HighOf 回读软限 memory.high（0 = 未设限）。
func HighOf(pid int) (int64, bool) { return currentLimit(pid, "memory.high") }

func currentLimit(pid int, file string) (int64, bool) {
	dir := cgroupDir(pid)
	if dir == "" {
		return 0, false
	}
	b, err := os.ReadFile(filepath.Join(dir, file))
	if err != nil {
		return 0, false
	}
	s := strings.TrimSpace(string(b))
	if s == "max" {
		return 0, true // 读到了，只是还没设限
	}
	n, err := strconv.ParseInt(s, 10, 64)
	return n, err == nil
}

// SetHigh 单独调一个 pane 的软限，**硬顶 memory.max 一动不动**（那是 L1 的事）。
//
// 总量闸用它踩刹车：软限只让内核激进回收 + throttle 住分配，不触发 OOM kill。
// 传 0 表示松开，交还给 L1 设的默认值。
func SetHigh(pid int, bytes int64) error {
	if !available() {
		// 这里**返回错误**，与 Apply 的「静默跳过」相反：Apply 在建会话路径上，
		// 护栏装不上就该降级成「和以前一样」，绝不能因此开不出会话；
		// 而这条路的调用方要靠返回值判断刹车到底踩没踩上 —— 报成功而实际没做，
		// 就会告诉用户「已给它减速」，用户于是不再管它，机器接着爆。
		return errors.New("memguard: 这台机器上装不了内存护栏")
	}
	val := "infinity"
	if bytes > 0 {
		val = strconv.FormatInt(bytes, 10)
	}
	deadline := time.Now().Add(applyWait)
	var lastErr error
	for {
		if cgroupPath(pid) == "" {
			return nil // 进程没了，没什么好设的
		}
		if unit := ScopeOf(pid); unit != "" {
			if err := exec.Command("systemctl", "--user", "set-property", unit, "MemoryHigh="+val).Run(); err != nil {
				lastErr = err
			} else if got, ok := HighOf(pid); ok && got == bytes {
				return nil // 与 Apply 同一条教训：判据是回读到了要的值，不是命令返回 0
			}
		}
		if time.Now().After(deadline) {
			if lastErr != nil {
				return lastErr
			}
			return fmt.Errorf("memguard: 软限 %s 未在 %v 内生效", val, applyWait)
		}
		time.Sleep(applyRetry)
	}
}

// parseBytes 把 "8G" / "6442450944" / "2000M" 解析成字节数。
// systemd 的额度写法用 1024 进制（G = GiB），这里与它保持一致。
func parseBytes(s string) (int64, bool) {
	s = strings.TrimSpace(s)
	if s == "" {
		return 0, false
	}
	i := 0
	for i < len(s) && s[i] >= '0' && s[i] <= '9' {
		i++
	}
	if i == 0 {
		return 0, false
	}
	n, err := strconv.ParseInt(s[:i], 10, 64)
	if err != nil {
		return 0, false
	}
	switch strings.ToUpper(strings.TrimSuffix(strings.TrimSpace(s[i:]), "iB")) {
	case "":
		return n, true
	case "K":
		return n << 10, true
	case "M":
		return n << 20, true
	case "G":
		return n << 30, true
	case "T":
		return n << 40, true
	}
	return 0, false
}

// Current 读一个 pane 所在 scope 的当前用量与峰值（字节）。ok=false 表示读不到。
// 会话列表的内存条和台账的 peak_rss 都从这里取——cgroup 本来就按 pane 分好了，
// 一次读一个文件，比轮询 ps 聚合整棵进程树便宜得多也准得多。
func Current(pid int) (cur, peak int64, ok bool) {
	dir := cgroupDir(pid)
	if dir == "" {
		return 0, 0, false
	}
	// 取 memory.stat 的 anon，**不是 memory.current**。
	//
	// current 把 page cache 一起算进来，而那是内核为加速留的、内存紧张时自己就会
	// 回收的东西。实测本机一个会话跑完两次交叉编译后 current=4.37G，其中 anon 只有
	// 0.75G（= claude 进程那 743MB），file 占 3.43G；往 memory.reclaim 写 2G，
	// current 当场掉到 2.32G，而进程一个字节没动。
	//
	// 拿 current 画内存条，用户看到 4.4G 会以为漏了；看门狗按它算百分比更会凭空
	// 报警——真实压力根本没到。所以只报 anon：它才是「这个会话吃了多少」。
	//
	// **peak 走另一套口径，故意的。**
	//
	// 它取内核记的 memory.peak（含 cache），而不是 anon 的采样最大值。
	// 因为两者服务不同目的：
	//   - cur 是「现在吃了多少」，天天在列表上看，必须准 → anon
	//   - peak 是「涨到过多少」，事后取证用，**绝不能漏尖峰** → memory.peak
	// 撞顶到进程被杀是毫秒级的事，5 秒一次的采样必然错过；靠 anon 采样取最大，
	// 查出来的 peak 会是 0（实测如此），那正好把最该看见的那一刻丢了。
	// 代价是 peak 偏高（含缓存），所以它是**上界**不是精确值——用它定位
	// 「是哪个会话」够了，别拿它算百分比。
	anon, ok1 := statField(filepath.Join(dir, "memory.stat"), "anon")
	if !ok1 {
		// 老内核没有 anon 这一行时退回 current：偏高，但总比没有强。
		anon, ok1 = readInt(filepath.Join(dir, "memory.current"))
	}
	peak, _ = readInt(filepath.Join(dir, "memory.peak")) // 缺了不算失败
	if peak < anon {
		peak = anon
	}
	return anon, peak, ok1
}

// statField 从 memory.stat 里取一个字段（每行 `<名字> <值>`）。
func statField(path, key string) (int64, bool) {
	b, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}
	for _, line := range strings.Split(string(b), "\n") {
		k, v, ok := strings.Cut(strings.TrimSpace(line), " ")
		if !ok || k != key {
			continue
		}
		n, err := strconv.ParseInt(strings.TrimSpace(v), 10, 64)
		return n, err == nil
	}
	return 0, false
}

// OOMKilled 返回这个 scope 里发生过几次 cgroup OOM。
// 会话没了时用它区分「撞了内存上限」和「被杀/正常退出」——台账据此记 died_reason='oom'。
func OOMKilled(pid int) int64 {
	dir := cgroupDir(pid)
	if dir == "" {
		return 0
	}
	ev, err := os.ReadFile(filepath.Join(dir, "memory.events"))
	if err != nil {
		return 0
	}
	for _, ln := range strings.Split(string(ev), "\n") {
		if k, v, ok := strings.Cut(strings.TrimSpace(ln), " "); ok && k == "oom_kill" {
			n, _ := strconv.ParseInt(v, 10, 64)
			return n
		}
	}
	return 0
}

func readInt(path string) (int64, bool) {
	b, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}
	n, err := strconv.ParseInt(strings.TrimSpace(string(b)), 10, 64)
	return n, err == nil
}

// scaleBytes 把 "8G" 这样的额度按比例缩小，返回**字节数**（systemd 认纯数字）。
//
// 不保留原单位：那样得在单位上做整数除法，6G 的 75% 会被截成 "4G" 而不是 4.5G
// ——软限凭空少了半个 G，而且只在不整除的额度上出错（8G→6G 正好整除，看不出来）。
// 认不出的写法返回空串：宁可不设软限，也别把 MemoryHigh 设成一个错的值。
func scaleBytes(s string, ratio float64) string {
	n, ok := parseBytes(s)
	if !ok {
		return ""
	}
	return strconv.FormatInt(int64(float64(n)*ratio), 10)
}

// SwapFree 交换区还剩多少（字节，读不到 0）。zram 交换设备也算在里面 ——
// 对「回收出来的匿名页往哪儿放」这个问题，压缩块设备和磁盘 swap 是同一类答案。
func SwapFree() int64 { return meminfoBytes("SwapFree:") }

// SwapOf 这个 pane 已经被挤到交换区（含 zram）的字节数。
// 总量闸靠它认出「这一轮压过了没有」——和 Braked() 一样，状态从内核读，不自己记。
func SwapOf(pid int) (int64, bool) {
	dir := cgroupDir(pid)
	if dir == "" {
		return 0, false
	}
	return readInt(filepath.Join(dir, "memory.swap.current"))
}

// 写 memory.reclaim 是**同步**的：内核回收够了（或放弃）才返回。会话列表每刷新
// 一次就会走到这里，压太多会把列表卡住，所以单轮压一小口 + 等一小会儿，
// 剩下的留给下一轮 —— 已经挤出去的那部分不会退回来。
const reclaimWait = 900 * time.Millisecond

// Reclaim 让内核把这个 pane 所在 scope 的 bytes 字节挤出去（写 memory.reclaim）。
//
// 这是总量闸的「先压后踩」里的**压**：把冷的匿名页压进 zram，进程照常跑。
// 和踩刹车（memory.high）的区别是关键的一点 —— 软限不回收内存，它只是让内核在
// 这个会话的**每一次分配**上做直接回收，回收得出来才叫减速；回收不出来就是干转，
// PSI 跟着冲高，systemd-oomd 会把整条 scope 端掉（2026-09-06 22:09 就是这么没的）。
func Reclaim(pid int, bytes int64) error {
	if bytes <= 0 {
		return errors.New("memguard: 要压的字节数得是正数")
	}
	dir := cgroupDir(pid)
	if dir == "" {
		return errors.New("memguard: 读不到这个 pane 的 cgroup 路径")
	}
	// 判据是**交换区真的接住了页**，不是「写调用返回 0」——和 Apply / SetHigh 同一条
	// 教训。内核对压不动的请求既可能返回 EAGAIN，也可能拿 page cache 交差；
	// 报成功而实际一页没动，就会告诉用户「已经替你压过了」，于是他不再管它。
	before, _ := SwapOf(pid)
	path := filepath.Join(dir, "memory.reclaim")
	done := make(chan error, 1)
	go func() { done <- reclaimWrite(path, bytes) }()
	select {
	case err := <-done:
		if err != nil {
			return err
		}
	case <-time.After(reclaimWait):
		// 超时不算失败：内核这会儿正在压，压出去多少就算多少。
	}
	if after, ok := SwapOf(pid); !ok || after <= before {
		return errors.New("memguard: 压不动 —— 交换区一页也没接住")
	}
	return nil
}

func reclaimWrite(path string, bytes int64) error {
	n := strconv.FormatInt(bytes, 10)
	// swappiness=200：这一档要压的就是**匿名页**。默认档会先啃 page cache，
	// 而 agent 会话的大头是匿名页（cache 内核自己就会回收，不用我们催），
	// 啃完缓存压力还在。参数是 6.9 才有的，老内核认不出会整条拒掉（EINVAL），
	// 那就退回不带参数的写法。
	err := writeFile(path, n+" swappiness=200")
	if errors.Is(err, syscall.EINVAL) {
		err = writeFile(path, n)
	}
	if errors.Is(err, syscall.EAGAIN) {
		// 没凑够要的量。这是常态而不是错误：压出去的那部分算数，下一轮接着来。
		return nil
	}
	return err
}

func writeFile(path, content string) error {
	f, err := os.OpenFile(path, os.O_WRONLY, 0)
	if err != nil {
		return err
	}
	_, err = f.WriteString(content)
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	return err
}
