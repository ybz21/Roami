// android_avd.go：本机模拟器(AVD)的发现与起停。
//
// AVD 是 Android SDK 的模拟器（QEMU + KVM），ttmux 直接管它的生命周期：列出来、起、停。
// 与之相对，network/device 两档只能连和断——「谁能起停它」就是三种来源的分界线。
//
// 两条容易踩空的地方：
//   - 模拟器要活得比 ttmux 久，所以启动走 setsid 脱离进程组；重启后端不该把用户的机器带走。
//   - 「这台 AVD 是不是已经在跑」只有模拟器控制台答得了（avdOfSerial），adb 那边只有 serial。
package phone

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/ybz21/Roami/internal/procctl"
)

// sdkRoot 定位 Android SDK：环境变量优先，再试各平台默认位置。
func sdkRoot() string {
	for _, e := range []string{"ANDROID_SDK_ROOT", "ANDROID_HOME"} {
		if v := strings.TrimSpace(os.Getenv(e)); v != "" {
			return v
		}
	}
	home, _ := os.UserHomeDir()
	if home == "" {
		return ""
	}
	for _, p := range []string{
		filepath.Join(home, "Android", "Sdk"),            // Linux 默认
		filepath.Join(home, "Library", "Android", "sdk"), // macOS 默认
	} {
		if st, err := os.Stat(p); err == nil && st.IsDir() {
			return p
		}
	}
	return ""
}

// sdkTool 定位 SDK 里的可执行文件（emulator / sdkmanager / avdmanager）；SDK 内找不到再回落 PATH。
func sdkTool(name string) string {
	if root := sdkRoot(); root != "" {
		cands := []string{filepath.Join(root, "cmdline-tools", "latest", "bin", name),
			filepath.Join(root, "tools", "bin", name)}
		if name == "emulator" {
			cands = []string{filepath.Join(root, "emulator", name)}
		}
		for _, p := range cands {
			if st, err := os.Stat(p); err == nil && !st.IsDir() {
				return p
			}
		}
	}
	if p, err := exec.LookPath(name); err == nil {
		return p
	}
	return ""
}

// avdDir：模拟器启动日志等落在配置同目录下的 android/（默认 ~/.roami/android）。
func avdDir() string {
	cfgStore.mu.Lock()
	f := cfgStore.file
	cfgStore.mu.Unlock()
	base := ""
	if f != "" {
		base = filepath.Dir(f)
	}
	if base == "" {
		home, _ := os.UserHomeDir()
		base = filepath.Join(home, ".roami")
	}
	d := filepath.Join(base, "android")
	_ = os.MkdirAll(d, 0o755)
	return d
}

// listAVDs 列出本机所有 AVD（含没跑起来的）——设置页要把它们都摆出来，否则停掉一台就从 UI 上消失了。
func listAVDs() []string {
	bin := sdkTool("emulator")
	if bin == "" {
		return nil
	}
	out, err := runCmd(10*time.Second, bin, "-list-avds")
	if err != nil {
		return nil
	}
	var names []string
	for _, ln := range strings.Split(string(out), "\n") {
		ln = strings.TrimSpace(ln)
		// 部分 SDK 版本会先打一行 INFO/告警；AVD 名不含空白，据此滤掉。
		if ln == "" || strings.ContainsAny(ln, " \t") {
			continue
		}
		names = append(names, ln)
	}
	return names
}

// avdOfSerial 问一台运行中的 emulator-xxxx 它是哪个 AVD（模拟器控制台命令，输出以 OK 收尾）。
// 没有它就分不清「运行中的 emulator-5554」和「未运行的 xh_tv1080p」是不是同一台，列表会出双份。
func avdOfSerial(serial string) string {
	if !strings.HasPrefix(serial, "emulator-") {
		return ""
	}
	out, err := runCmd(4*time.Second, "adb", "-s", serial, "emu", "avd", "name")
	if err != nil {
		return ""
	}
	for _, ln := range strings.Split(string(out), "\n") {
		ln = strings.TrimSpace(ln)
		if ln == "" || ln == "OK" || strings.HasPrefix(ln, "KO") {
			continue
		}
		return ln
	}
	return ""
}

// runningAVDs 返回 AVD 名 → serial（只问一遍控制台，供设备列表/状态复用）。
func runningAVDs(list []androidDev) map[string]string {
	m := map[string]string{}
	for _, d := range list {
		if n := avdOfSerial(d.Serial); n != "" {
			m[n] = d.Serial
		}
	}
	return m
}

// serialOfAVD 返回某个 AVD 当前的 serial；没跑起来回空。
//
// 带 3s 缓存：它要跑 adb devices + 每台一次控制台问询，而 target() 每条 adb 命令都会问一遍——
// 镜像推流按帧调，不缓存等于给每一帧加两次 adb 往返。
var avdSerialCache struct {
	mu             sync.Mutex
	name, serial   string
	at             time.Time
	haveCachedName bool
}

func serialOfAVD(name string) string {
	if name == "" {
		return ""
	}
	avdSerialCache.mu.Lock()
	if avdSerialCache.haveCachedName && avdSerialCache.name == name && time.Since(avdSerialCache.at) < 3*time.Second {
		s := avdSerialCache.serial
		avdSerialCache.mu.Unlock()
		return s
	}
	avdSerialCache.mu.Unlock()

	got := ""
	for _, d := range androidImpl.devices() {
		if strings.HasPrefix(d.Serial, "emulator-") && avdOfSerial(d.Serial) == name {
			got = d.Serial
			break
		}
	}
	avdSerialCache.mu.Lock()
	avdSerialCache.name, avdSerialCache.serial = name, got
	avdSerialCache.at, avdSerialCache.haveCachedName = time.Now(), true
	avdSerialCache.mu.Unlock()
	return got
}

// avdRef 是「选了一台还没运行的 AVD」的目标写法，与前端设备列表的 id 同形。
// 让它带前缀而不是留空很重要：留空会落到 adb 默认设备，于是点了模拟器却操作了旁边插着的真机。
func avdRef(name string) string { return "avd:" + name }

func avdNameFromRef(ref string) string { return strings.TrimPrefix(ref, "avd:") }

// gpuMode 挑渲染后端。
//
// **先看有没有显示**：-gpu host 走的是 GLX/EGL，要一个 X/Wayland 显示才拿得到 EGL display。
// roam 后端常年是 systemd 用户服务，DISPLAY 是空的，那里 host 必然失败——日志里写着
// 「Failed to get EGL display / Could not start renderer」，而 UI 上只剩一句「启动超时」。
// 有独显也没用：显卡在，能画的那块屏不在。
//
// 有显示时才谈硬件加速：Intel(0x8086)/AMD(0x1002) 走 host，
// 跳过 NVIDIA(0x10de)——其专有驱动下 SurfaceFlinger 常起不来（redroid 时代同样的坑）。
func gpuMode() string {
	if runtime.GOOS != "linux" {
		return "auto" // macOS/Windows 交给模拟器自己挑（有 Metal/ANGLE 后端）
	}
	return linuxGPUMode(os.Getenv("DISPLAY"), os.Getenv("WAYLAND_DISPLAY"), drmVendors())
}

// drmVendors 读出本机各渲染节点的 PCI 厂商号。
func drmVendors() []string {
	nodes, _ := filepath.Glob("/sys/class/drm/renderD*/device/vendor")
	var out []string
	for _, n := range nodes {
		if b, err := os.ReadFile(n); err == nil {
			out = append(out, strings.TrimSpace(string(b)))
		}
	}
	return out
}

// linuxGPUMode 是上面那条判断的纯函数部分。
func linuxGPUMode(display, wayland string, vendors []string) string {
	if strings.TrimSpace(display) == "" && strings.TrimSpace(wayland) == "" {
		return "swiftshader_indirect" // 无头：只有软件渲染起得来
	}
	for _, v := range vendors {
		switch v {
		case "0x8086", "0x1002":
			return "host"
		}
	}
	return "swiftshader_indirect"
}

// avdStartMu 串行化启动：重复点击不该起出第二个 qemu 进程（同名 AVD 第二个会因锁失败，只留一堆日志）。
var avdStartMu sync.Mutex

// startAVD 起一台 AVD 并等它开机完成，返回 serial。
// wipe=true 走 -wipe-data（冷启动，清用户数据）。
func startAVD(name string, wipe bool) (string, error) {
	if name == "" {
		return "", errors.New("缺少 AVD 名")
	}
	bin := sdkTool("emulator")
	if bin == "" {
		return "", errors.New("未找到 emulator（装 Android SDK 的 Emulator 组件）")
	}
	if !avdStartMu.TryLock() {
		return "", errors.New("已有模拟器正在启动，请稍候")
	}
	defer avdStartMu.Unlock()
	if s := serialOfAVD(name); s != "" && !wipe {
		return s, nil // 已在跑：直接复用
	}
	// KVM 先于启动检查：没有它 x86_64 镜像根本起不来，而 emulator 的原始报错埋在日志里，
	// UI 上只剩一句「启动超时」——白等三分钟。
	kvm := kvmOK
	if runtime.GOOS == "linux" {
		st, err := kvmState()
		if st != kvmOK && st != kvmViaGroup {
			return "", err
		}
		kvm = st
	}
	logPath := filepath.Join(avdDir(), "avd-"+name+".log")
	lf, err := os.Create(logPath)
	if err != nil {
		return "", fmt.Errorf("打不开启动日志 %s: %w", logPath, err)
	}
	defer lf.Close()
	args := []string{"-avd", name, "-no-window", "-no-audio", "-no-boot-anim", "-accel", "on", "-gpu", gpuMode()}
	if wipe {
		args = append(args, "-wipe-data")
	}
	// 组里加过 kvm 但本进程没带上时套一层 sg：那一格不套就永远起不来，
	// 而用户已经照我们说的跑过 sudo 了 —— 再让他「重新登录一次」是我们没做完事。
	spawnBin, spawnArgs := kvmSpawn(kvm, bin, args)
	cmd := exec.Command(spawnBin, spawnArgs...)
	// Setsid：脱离 ttmux 的会话与进程组。后端重启/退出不能把用户的模拟器一起带走。
	procctl.SetDetached(cmd)
	cmd.Stdout, cmd.Stderr = lf, lf
	if err := cmd.Start(); err != nil {
		return "", fmt.Errorf("启动模拟器失败: %w", err)
	}
	go func() { _ = cmd.Wait() }() // 只为回收僵尸；进程已 setsid，不随我们生死
	serial, err := waitAVDBoot(name, 180*time.Second)
	if err != nil && serial == "" {
		// 连 adb 都没登记过 = 它压根没起来（渲染器初始化失败就是这样）。
		// 这种壳子必须收掉：它会一直握着 AVD 的 multiinstance.lock，
		// 下一次点「启动」只换来一句 "AVD is already running" ——
		// 一次失败毒死后面每一次。（同 AGENTS.md 那条：send 失败就 kill 掉刚建的会话。）
		killProcessGroup(cmd.Process)
	}
	return serial, err
}

// killProcessGroup 收掉整棵进程树。emulator 会再 fork 出 qemu-system 与 crashpad，
// 只 kill 首进程会留下一堆孤儿，AVD 的锁也还在它们手上；进程已 setsid，pgid 就是它自己。
func killProcessGroup(p *os.Process) {
	procctl.TerminateGroup(p, 500*time.Millisecond)
}

// waitAVDBoot 等 serial 出现并等到 sys.boot_completed=1。
func waitAVDBoot(name string, timeout time.Duration) (string, error) {
	deadline := time.Now().Add(timeout)
	serial := ""
	for time.Now().Before(deadline) {
		if serial == "" {
			serial = serialOfAVD(name)
		}
		if serial != "" {
			out, _ := runCmd(4*time.Second, "adb", "-s", serial, "shell", "getprop", "sys.boot_completed")
			if strings.TrimSpace(string(out)) == "1" {
				return serial, nil
			}
		}
		time.Sleep(2 * time.Second)
	}
	if serial != "" {
		return serial, fmt.Errorf("模拟器 %s 已起但未开机完成（看日志 %s）", name, filepath.Join(avdDir(), "avd-"+name+".log"))
	}
	return "", fmt.Errorf("模拟器 %s 启动超时（看日志 %s）", name, filepath.Join(avdDir(), "avd-"+name+".log"))
}

// stopAVD 关掉一台运行中的模拟器（整机关机，不只是断开 adb）。
func stopAVD(serial string) error {
	if serial == "" || !strings.HasPrefix(serial, "emulator-") {
		return errors.New("不是本机模拟器，无法停止")
	}
	_, err := runCmd(15*time.Second, "adb", "-s", serial, "emu", "kill")
	return err
}

// avdLogTail 回启动日志的尾部，供 UI 的日志区显示失败原因。
func avdLogTail(name string, maxBytes int) string {
	b, err := os.ReadFile(filepath.Join(avdDir(), "avd-"+name+".log"))
	if err != nil {
		return ""
	}
	if len(b) > maxBytes {
		b = b[len(b)-maxBytes:]
	}
	return string(b)
}
