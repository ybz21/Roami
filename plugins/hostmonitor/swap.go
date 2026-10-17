package hostmonitor

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

// 清空交换空间：`swapoff -a` 把换出去的页全部读回内存,`swapon -a` 再挂回来。
//
// 为什么值得做一个按钮:swap 用满是**整机卡死的前兆**——换页无处可去,内核就在直接
// 回收里空转,ping 还通(内核收发 ICMP 不换页)但 ssh 再也进不来,只能按电源键。
// 本机 2026-08-12 那次就是这么冻的。而在冻住之前,把换出去的页拉回内存能立刻缓解。
//
// 但这条命令自己就能把机器打死:swapoff 是**同步**的,它要把已用的 swap 一次性读回
// 内存;装不下的时候 OOM killer 当场开枪,而它挑的多半是最大的那个进程——也就是你正
// 在跑的 agent。所以判据必须在动手之前算清楚,而不是「试试看」。

// 读回来之后至少要给系统留这么多余量。1 GiB 是拍的,但拍在保守那一边:
// 判定和执行之间隔着几秒,这几秒里内存还在动。
const swapHeadroomBytes = uint64(1) << 30

// SwapPlan 是「能不能清」的判定结果,也是确认框上要给人看的三个数。
type SwapPlan struct {
	SwapUsed  uint64 `json:"swapUsed"`
	Available uint64 `json:"available"` // MemAvailable
	Headroom  uint64 `json:"headroom"`  // 读回来之后还剩多少
	OK        bool   `json:"ok"`
	Reason    string `json:"reason,omitempty"` // ok=false 时的机器可读原因
}

// planSwapClear 是纯函数:喂两个数就能断言,不必真去动 swap。
func planSwapClear(swapUsed, memAvailable uint64) SwapPlan {
	p := SwapPlan{SwapUsed: swapUsed, Available: memAvailable}
	if swapUsed == 0 {
		p.Reason = "empty"
		return p
	}
	// 无符号数:先比较再相减,否则装不下的时候会绕回一个巨大的 Headroom
	if memAvailable < swapUsed+swapHeadroomBytes {
		p.Reason = "wont-fit"
		return p
	}
	p.Headroom = memAvailable - swapUsed
	p.OK = true
	return p
}

// ── 后台任务 ──────────────────────────────────────────────────────────────
//
// swapoff 把 7 GB 换出去的页读回内存要好几十秒到几分钟,而 `plugin run` 是一次性
// 进程、请求要一直挂着等它——页面转圈、超时、刷新一下就不知道还在不在跑。
// 所以拆成两段:apply 只**起一个脱离的子进程**就返回,状态写进 StorageDir;
// 页面轮询 status 看进度(swap 还剩多少)。
//
// 子进程跑的是这个插件自己的 swap-cycle 命令(`roami plugin run host-monitor.swap-cycle`),
// 不是 `sh -c "swapoff -a && swapon -a"`:后者要往权限白名单里塞一个 shell,
// 而白名单上现在只有 swapoff / swapon 两条,这是它值钱的地方。
// swapoff 与 swapon 的先后顺序由那个子进程自己保证——它会一直活到两条都跑完,
// 哪怕点完就关页面。

const swapJobFile = "swap-clear.json"

// swapJob 是后台任务的状态,落在 StorageDir(插件进程一次性,跨调用只能靠文件)。
type swapJob struct {
	PID       int    `json:"pid"`
	StartedAt int64  `json:"startedAt"` // Unix 秒
	StartSwap uint64 `json:"startSwap"` // 起步时换出去多少,用来算进度
	Finished  bool   `json:"finished"`  // 子进程写:两条命令都跑完了
	Err       string `json:"err,omitempty"`
}

// SwapStatus 是 status=1 的返回:页面据此画进度条和结果。
type SwapStatus struct {
	State     string `json:"state"` // idle | running | done | failed
	StartSwap uint64 `json:"startSwap"`
	SwapUsed  uint64 `json:"swapUsed"` // 此刻还剩多少没读回来
	Available uint64 `json:"available"`
	ElapsedMs int64  `json:"elapsedMs"`
	Err       string `json:"err,omitempty"`
}

func jobPath(ctx *sdk.Ctx) string { return filepath.Join(ctx.StorageDir, swapJobFile) }

func readJob(ctx *sdk.Ctx) swapJob {
	var j swapJob
	b, err := os.ReadFile(jobPath(ctx))
	if err != nil {
		return j
	}
	_ = json.Unmarshal(b, &j)
	return j
}

func writeJob(ctx *sdk.Ctx, j swapJob) error {
	if err := os.MkdirAll(ctx.StorageDir, 0o755); err != nil { // StorageDir 不保证已存在
		return err
	}
	b, _ := json.Marshal(j)
	return os.WriteFile(jobPath(ctx), b, 0o644)
}

// alive 判进程还在不在。信号 0 不真发信号,只做权限与存在性检查。
func alive(pid int) bool {
	if pid <= 0 {
		return false
	}
	p, err := os.FindProcess(pid) // Unix 上这一步从不失败
	if err != nil {
		return false
	}
	return p.Signal(syscall.Signal(0)) == nil
}

func swapStatus(ctx *sdk.Ctx) (SwapStatus, error) {
	mem, err := currentMem()
	if err != nil {
		return SwapStatus{}, err
	}
	j := readJob(ctx)
	st := SwapStatus{State: "idle", StartSwap: j.StartSwap, SwapUsed: mem.SwapUsed, Available: mem.Available, Err: j.Err}
	if j.StartedAt > 0 {
		st.ElapsedMs = time.Since(time.Unix(j.StartedAt, 0)).Milliseconds()
	}
	switch {
	case j.PID == 0:
		return st, nil
	case !j.Finished && alive(j.PID):
		st.State = "running"
	case j.Err != "":
		st.State = "failed"
	case j.Finished:
		st.State = "done"
	default:
		// 进程没了、也没写完成标记:被杀了或者机器重启了。swap 是不是空的说了算。
		st.State = "failed"
		if mem.SwapUsed == 0 {
			st.State = "done"
		} else if st.Err == "" {
			st.Err = "interrupted"
		}
	}
	return st, nil
}

// swapClear 是 host-monitor.swap-clear 命令。
//
// 三种用法:
//   - 不带参数 = 只回判定(给确认框用),**默认不动手**——这条命令的代价不可撤销
//     (被 OOM 杀掉的进程回不来);
//   - status=1 = 查后台任务进度;
//   - apply=1  = 起后台任务,立刻返回。
func swapClear(ctx *sdk.Ctx, args map[string]string) (any, error) {
	if args["status"] == "1" {
		return swapStatus(ctx)
	}
	mem, err := currentMem()
	if err != nil {
		return nil, err
	}
	plan := planSwapClear(mem.SwapUsed, mem.Available)
	if args["apply"] != "1" {
		return plan, nil
	}
	if !plan.OK {
		return plan, fmt.Errorf("swap-clear refused: %s", plan.Reason)
	}
	if j := readJob(ctx); !j.Finished && alive(j.PID) {
		return swapStatus(ctx) // 已经在跑了,别起第二个:两个 swapoff 抢同一块内存
	}
	pid, err := startSwapCycle()
	if err != nil {
		return plan, err
	}
	if err := writeJob(ctx, swapJob{PID: pid, StartedAt: time.Now().Unix(), StartSwap: mem.SwapUsed}); err != nil {
		return plan, err
	}
	return SwapStatus{State: "running", StartSwap: mem.SwapUsed, SwapUsed: mem.SwapUsed, Available: mem.Available}, nil
}

// startSwapCycle 起一个**脱离**的子进程去跑 swap-cycle,返回它的 pid。
// Setsid:插件进程马上就退出了,不脱离的话子进程会跟着一起走。
func startSwapCycle() (int, error) {
	self, err := os.Executable()
	if err != nil {
		return 0, err
	}
	cmd := exec.Command(self, "plugin", "run", "host-monitor.swap-cycle")
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	cmd.Stdin, cmd.Stdout, cmd.Stderr = nil, nil, nil
	if err := cmd.Start(); err != nil {
		return 0, err
	}
	go func() { _ = cmd.Wait() }() // 不收尸的话这一小会儿里它是僵尸;本进程马上退出,收不到也无妨
	return cmd.Process.Pid, nil
}

// swapCycle 是 host-monitor.swap-cycle:真正干活的那一段,同步跑完两条命令再写状态。
// 它由 swapClear 起的子进程调用,自己就是那个「后台任务」——页面不等它。
func swapCycle(ctx *sdk.Ctx, _ map[string]string) (any, error) {
	j := readJob(ctx)
	j.PID = os.Getpid()
	if j.StartedAt == 0 {
		j.StartedAt = time.Now().Unix()
	}
	if j.StartSwap == 0 {
		if mem, err := currentMem(); err == nil {
			j.StartSwap = mem.SwapUsed
		}
	}
	_ = writeJob(ctx, j)

	err := runSwapCycle()
	j.Finished = true
	if err != nil {
		j.Err = err.Error()
	}
	_ = writeJob(ctx, j)
	if err != nil {
		return nil, err
	}
	return swapStatus(ctx)
}

// runSwapCycle 走 sudo -n。**不接口令**:插件进程没有终端,交互式 sudo 只会挂死;
// 而把口令放进配置项是另一个更糟的主意。没开免密时给出那一行 sudoers,让人自己开。
func runSwapCycle() error {
	for _, argv := range [][]string{{"swapoff", "-a"}, {"swapon", "-a"}} {
		cmd := exec.Command("sudo", append([]string{"-n"}, argv...)...)
		out, err := cmd.CombinedOutput()
		if err == nil {
			continue
		}
		msg := strings.TrimSpace(string(out))
		if strings.Contains(msg, "password") || strings.Contains(msg, "口令") || msg == "" {
			return fmt.Errorf("need-sudo")
		}
		return fmt.Errorf("%s failed: %s", strings.Join(argv, " "), msg)
	}
	return nil
}

// currentMem 读一次 /proc/meminfo。判定用的是**此刻**的数,不用采样缓存里那份——
// 缓存最久可能是 3 秒前的,而这三秒里 swap 可能又涨了几百兆。
func currentMem() (MemStat, error) {
	b, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return MemStat{}, err
	}
	return parseMeminfo(string(b)), nil
}
