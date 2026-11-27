// ios.go：iOS 后端（macOS），镜像/启动靠 `xcrun simctl`，点按/输入/读结构靠 `idb`。
//
// 与 android.go 同构,实现同一个 Device 接口；NewDevice() 在 darwin 上返回它,前端/WS/路由复用。
//
// ⚠ 本文件未在真机/真 Mac 上跑过(开发环境是 Linux)。按 simctl/idb 公开行为编写,
//
//	Mac 上首次启用需联调。依赖:Xcode(simctl) + idb(`brew install idb-companion && pip install fb-idb`)。
//	simctl 无通用 tap,所以点按/输入/读结构强依赖 idb;缺 idb 时 health 明示降级。
package phone

import (
	"bytes"
	"encoding/json"
	"fmt"
	"image"
	"image/jpeg"
	_ "image/png" // 真机 idb 截图是 PNG，注册解码器
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/procctl"
)

type iosDevice struct{}

func newIOSDevice() *iosDevice { return &iosDevice{} }

// target 返回模拟器/设备 UDID；配置 Address 为空时用 "booted"（当前已启动的那台）。
func (d *iosDevice) target() string {
	if a := strings.TrimSpace(iosCfg().Address); a != "" {
		return a
	}
	return "booted"
}

func haveIDB() bool { _, err := exec.LookPath("idb"); return err == nil }

// runCmd 跑任意命令并带超时，返回 stdout（出错带 stderr 摘要）。
// 用独立进程组启动：超时时 kill 整个进程组，连带杀掉命令 spawn 的子进程
// （如 bash→brew→curl）。否则只杀父进程会留下孤儿——brew 下载孤儿仍持有下载锁，
// 导致下次安装撞锁失败（“已被另一个 brew install 进程锁定”）。
func runCmd(timeout time.Duration, name string, args ...string) ([]byte, error) {
	cmd := exec.Command(name, args...)
	procctl.SetProcessGroup(cmd) // 自成进程组，pgid = pid
	var out, errb bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &errb
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("%s 启动失败: %w", name, err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		if err != nil {
			msg := strings.TrimSpace(errb.String())
			if msg == "" {
				msg = err.Error()
			}
			return out.Bytes(), fmt.Errorf("%s", msg)
		}
		return out.Bytes(), nil
	case <-time.After(timeout):
		// 负 pid = 向整个进程组发信号；先 TERM 给子进程善后机会，再兜底 KILL。
		pgid := cmd.Process.Pid
		procctl.SignalGroup(pgid, false)
		go func() { time.Sleep(2 * time.Second); procctl.SignalGroup(pgid, true) }()
		_ = cmd.Process.Kill()
		return nil, fmt.Errorf("%s 超时", name)
	}
}

func (d *iosDevice) simctl(timeout time.Duration, args ...string) ([]byte, error) {
	return runCmd(timeout, "xcrun", append([]string{"simctl"}, args...)...)
}

// idb 调用：把 --udid <udid> 追加到命令末尾（fb-idb 的 argparse 允许选项在位置参数之后；
// 放在子命令路径之前会被当成 group 的参数而出错）。需 idb 在 PATH。
func (d *iosDevice) idb(timeout time.Duration, args ...string) ([]byte, error) {
	full := append([]string{}, args...)
	if udid := d.resolveUDID(); udid != "" {
		full = append(full, "--udid", udid)
	}
	return runCmd(timeout, "idb", full...)
}

var udidRe = regexp.MustCompile(`\(([0-9A-Fa-f-]{36})\) \(Booted\)`)

// isDevice 真机(物理 iPhone)模式 —— 截图/启动走 idb；模拟器模式走 simctl。
func (d *iosDevice) isDevice() bool { return iosCfg().Mode == "device" }

// resolveUDID 解析目标 UDID：真机/指定 UDID 原样返回；模拟器留空("booted")时找当前已启动的。
func (d *iosDevice) resolveUDID() string {
	t := d.target()
	if t != "booted" && t != "" {
		return t
	}
	if d.isDevice() {
		return "" // 真机必须显式给 UDID（从设备列表里选）
	}
	out, err := d.simctl(4*time.Second, "list", "devices", "booted")
	if err != nil {
		return ""
	}
	if m := udidRe.FindStringSubmatch(string(out)); m != nil {
		return m[1]
	}
	return ""
}

func (d *iosDevice) booted() bool { return d.resolveUDID() != "" }

func (d *iosDevice) Ensure() error {
	if _, err := exec.LookPath("xcrun"); err != nil {
		return fmt.Errorf("未找到 xcrun（装 Xcode 命令行工具）")
	}
	if d.isDevice() { // 真机：不 boot，需 idb 且选了 UDID
		if !haveIDB() {
			return fmt.Errorf("iOS 真机需 idb（brew install idb-companion && pip install fb-idb）")
		}
		if d.resolveUDID() == "" {
			return fmt.Errorf("未选择 iOS 真机（在设置里从设备列表选一台 UDID）")
		}
		return nil
	}
	// 模拟器：指定了 UDID 但没启动 → 尝试 boot
	if t := d.target(); t != "booted" && t != "" && d.resolveUDID() == "" {
		_, _ = d.simctl(60*time.Second, "boot", t)
		_, _ = d.simctl(120*time.Second, "bootstatus", t, "-b")
	}
	if !d.booted() {
		return fmt.Errorf("无已启动的 iOS 模拟器（先启动，或在设置里选模拟器 UDID）")
	}
	return nil
}

func (d *iosDevice) Health() Status {
	if d.isDevice() {
		if !haveIDB() {
			return Status{OK: false, Platform: "ios", Error: "iOS 真机需 idb（brew install idb-companion && pip install fb-idb）"}
		}
		udid := d.resolveUDID()
		if udid == "" {
			return Status{OK: false, Platform: "ios", Error: "未选择 iOS 真机"}
		}
		return Status{OK: true, Platform: "ios", Device: udid}
	}
	if _, err := exec.LookPath("xcrun"); err != nil {
		return Status{OK: false, Platform: "ios", Error: "未找到 xcrun（装 Xcode 命令行工具）"}
	}
	udid := d.resolveUDID()
	if udid == "" {
		return Status{OK: false, Platform: "ios", Error: "无已启动的 iOS 模拟器"}
	}
	if !haveIDB() {
		return Status{OK: false, Platform: "ios", Device: udid,
			Error: "未装 idb，点按/输入不可用（brew install idb-companion && pip install fb-idb）"}
	}
	return Status{OK: true, Platform: "ios", Device: udid}
}

// CaptureJPEG：模拟器走 simctl(直出 jpeg)；真机走 idb screenshot(临时文件,PNG)→转 JPEG。
func (d *iosDevice) CaptureJPEG(quality int) ([]byte, int, int, error) {
	if quality < 10 {
		quality = 10
	} else if quality > 100 {
		quality = 100
	}
	if d.isDevice() {
		tmp, err := os.CreateTemp("", "ttmux-ios-*.png")
		if err != nil {
			return nil, 0, 0, err
		}
		name := tmp.Name()
		_ = tmp.Close()
		defer os.Remove(name)
		if _, err := d.idb(8*time.Second, "screenshot", name); err != nil {
			return nil, 0, 0, err
		}
		raw, err := os.ReadFile(name)
		if err != nil {
			return nil, 0, 0, err
		}
		img, _, err := image.Decode(bytes.NewReader(raw))
		if err != nil {
			return nil, 0, 0, fmt.Errorf("解码真机截图失败: %w", err)
		}
		var buf bytes.Buffer
		if err := jpeg.Encode(&buf, img, &jpeg.Options{Quality: quality}); err != nil {
			return nil, 0, 0, err
		}
		b := img.Bounds()
		return buf.Bytes(), b.Dx(), b.Dy(), nil
	}
	out, err := d.simctl(8*time.Second, "io", d.target(), "screenshot", "--type", "jpeg", "-")
	if err != nil {
		return nil, 0, 0, err
	}
	cfg, err := jpeg.DecodeConfig(bytes.NewReader(out))
	if err != nil {
		return nil, 0, 0, fmt.Errorf("解码截图失败: %w", err)
	}
	return out, cfg.Width, cfg.Height, nil
}

func (d *iosDevice) Tap(x, y int) error {
	if !haveIDB() {
		return fmt.Errorf("点按需 idb")
	}
	_, err := d.idb(5*time.Second, "ui", "tap", strconv.Itoa(x), strconv.Itoa(y))
	return err
}

func (d *iosDevice) Swipe(x1, y1, x2, y2, ms int) error {
	if !haveIDB() {
		return fmt.Errorf("滑动需 idb")
	}
	if ms <= 0 {
		ms = 300
	}
	dur := strconv.FormatFloat(float64(ms)/1000, 'f', 2, 64)
	_, err := d.idb(6*time.Second, "ui", "swipe",
		strconv.Itoa(x1), strconv.Itoa(y1), strconv.Itoa(x2), strconv.Itoa(y2), "--duration", dur)
	return err
}

func (d *iosDevice) Text(s string) error {
	if s == "" {
		return nil
	}
	if !haveIDB() {
		return fmt.Errorf("输入需 idb")
	}
	_, err := d.idb(5*time.Second, "ui", "text", s)
	return err
}

func (d *iosDevice) Key(name string) error {
	if !haveIDB() {
		return fmt.Errorf("按键需 idb")
	}
	switch name {
	case "home":
		_, err := d.idb(4*time.Second, "ui", "button", "HOME")
		return err
	case "lock", "power":
		_, err := d.idb(4*time.Second, "ui", "button", "LOCK")
		return err
	case "siri":
		_, err := d.idb(4*time.Second, "ui", "button", "SIRI")
		return err
	case "enter":
		_, err := d.idb(4*time.Second, "ui", "key", "40") // HID usage: Return
		return err
	case "back":
		return fmt.Errorf("iOS 无系统返回键（用边缘 swipe 替代）")
	default:
		return fmt.Errorf("未知按键: %s", name)
	}
}

// Apps 用 idb list-apps（管道分隔：bundle_id | name | ...）。
func (d *iosDevice) Apps() ([]App, error) {
	if !haveIDB() {
		// 无 idb 退化用 simctl（输出是 NeXTSTEP plist，难精确解析，这里仅抓 bundle id）
		out, err := d.simctl(8*time.Second, "listapps", d.target())
		if err != nil {
			return nil, err
		}
		var apps []App
		re := regexp.MustCompile(`CFBundleIdentifier\s*=\s*"?([A-Za-z0-9_.\-]+)"?`)
		seen := map[string]bool{}
		for _, m := range re.FindAllStringSubmatch(string(out), -1) {
			if !seen[m[1]] {
				seen[m[1]] = true
				apps = append(apps, App{ID: m[1]})
			}
		}
		return apps, nil
	}
	out, err := d.idb(8*time.Second, "list-apps")
	if err != nil {
		return nil, err
	}
	var apps []App
	for _, line := range strings.Split(string(out), "\n") {
		parts := strings.Split(line, "|")
		if len(parts) >= 1 {
			id := strings.TrimSpace(parts[0])
			if id == "" {
				continue
			}
			name := ""
			if len(parts) >= 2 {
				name = strings.TrimSpace(parts[1])
			}
			apps = append(apps, App{ID: id, Name: name})
		}
	}
	return apps, nil
}

func (d *iosDevice) Launch(id string) error {
	if id == "" {
		return fmt.Errorf("缺少 bundleId")
	}
	if d.isDevice() { // 真机走 idb launch（simctl 管不到物理机）
		_, err := d.idb(8*time.Second, "launch", id)
		return err
	}
	_, err := d.simctl(8*time.Second, "launch", d.target(), id)
	return err
}

// UIDump 用 idb ui describe-all 拿无障碍元素树。
func (d *iosDevice) UIDump() ([]Element, error) {
	if !haveIDB() {
		return nil, fmt.Errorf("读屏幕结构需 idb")
	}
	out, err := d.idb(8*time.Second, "ui", "describe-all")
	if err != nil {
		return nil, err
	}
	// idb 可能输出 JSON 数组,也可能逐行 JSON;两者都兼容
	var raw []struct {
		AXLabel string `json:"AXLabel"`
		Type    string `json:"type"`
		Frame   struct {
			X      float64 `json:"x"`
			Y      float64 `json:"y"`
			Width  float64 `json:"width"`
			Height float64 `json:"height"`
		} `json:"frame"`
	}
	trimmed := bytes.TrimSpace(out)
	if len(trimmed) > 0 && trimmed[0] == '[' {
		_ = json.Unmarshal(trimmed, &raw)
	} else {
		for _, line := range strings.Split(string(out), "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			var e struct {
				AXLabel string `json:"AXLabel"`
				Type    string `json:"type"`
				Frame   struct {
					X      float64 `json:"x"`
					Y      float64 `json:"y"`
					Width  float64 `json:"width"`
					Height float64 `json:"height"`
				} `json:"frame"`
			}
			if json.Unmarshal([]byte(line), &e) == nil {
				raw = append(raw, e)
			}
		}
	}
	clickableTypes := map[string]bool{"Button": true, "Cell": true, "Link": true, "TextField": true, "SearchField": true, "Switch": true}
	var els []Element
	for _, r := range raw {
		f := r.Frame
		if f.Width == 0 && f.Height == 0 && r.AXLabel == "" {
			continue
		}
		els = append(els, Element{
			Text:      r.AXLabel,
			Class:     r.Type,
			Clickable: clickableTypes[r.Type],
			X:         int(f.X + f.Width/2),
			Y:         int(f.Y + f.Height/2),
			Bounds:    [4]int{int(f.X), int(f.Y), int(f.X + f.Width), int(f.Y + f.Height)},
		})
	}
	return els, nil
}
