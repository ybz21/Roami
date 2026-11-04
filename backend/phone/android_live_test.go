package phone

// 联机测试仅在显式启用并指定设备时运行，普通门禁不操作已连接手机。
// 跑：ANDROID_SERIAL=<已确认序列号> ROAMI_PHONE_LIVE_TESTS=1 go test ./backend/phone -run TestLive -v

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func liveDev(t *testing.T) *androidDevice {
	if os.Getenv("ROAMI_PHONE_LIVE_TESTS") != "1" || os.Getenv("ANDROID_SERIAL") == "" {
		t.Skip("真机测试需显式启用 ROAMI_PHONE_LIVE_TESTS=1 并指定 ANDROID_SERIAL")
	}
	d := newAndroidDevice()
	if d.target() != os.Getenv("ANDROID_SERIAL") {
		t.Fatal("当前手机配置覆盖了 ANDROID_SERIAL，拒绝操作其他设备")
	}
	if d.state() != "device" {
		t.Skip("无已连接 Android 设备，跳过联机测试")
	}
	return d
}

func TestLiveHealth(t *testing.T) {
	d := liveDev(t)
	s := d.Health()
	if !s.OK {
		t.Fatalf("Health 不 OK: %+v", s)
	}
	t.Logf("Health: platform=%s device=%q", s.Platform, s.Device)
}

func TestLiveCapture(t *testing.T) {
	d := liveDev(t)
	jpg, w, h, err := d.CaptureJPEG(50)
	if err != nil {
		t.Fatalf("CaptureJPEG: %v", err)
	}
	if w == 0 || h == 0 || len(jpg) == 0 {
		t.Fatalf("空帧: w=%d h=%d bytes=%d", w, h, len(jpg))
	}
	t.Logf("截图 OK: %dx%d, JPEG %d 字节", w, h, len(jpg))
	if out := os.Getenv("PHONE_SHOT"); out != "" {
		_ = os.WriteFile(out, jpg, 0o644)
		t.Logf("已写出 %s", out)
	}
}

func TestLiveApps(t *testing.T) {
	d := liveDev(t)
	apps, err := d.Apps()
	if err != nil {
		t.Fatalf("Apps: %v", err)
	}
	t.Logf("第三方 App 数: %d", len(apps))
	for i, a := range apps {
		if i >= 5 {
			break
		}
		t.Logf("  - %s", a.ID)
	}
}

func TestLiveTapAndKey(t *testing.T) {
	d := liveDev(t)
	if err := d.Tap(360, 640); err != nil {
		t.Fatalf("Tap: %v", err)
	}
	if err := d.Key("home"); err != nil {
		t.Fatalf("Key home: %v", err)
	}
	t.Log("Tap + Key(home) OK")
}

func TestLiveUIDump(t *testing.T) {
	d := liveDev(t)
	els, err := d.UIDump()
	if err != nil {
		t.Fatalf("UIDump: %v", err)
	}
	t.Logf("UI 元素数: %d", len(els))
	for i, e := range els {
		if i >= 8 {
			break
		}
		t.Logf("  [%d,%d] clickable=%v text=%q desc=%q", e.X, e.Y, e.Clickable, e.Text, e.Desc)
	}
}

// TestLiveAVD 探本机模拟器：列 AVD、把运行中的 serial 反查回 AVD 名。
// 这是设备列表去重的支点——反查不出来，列表就会出「运行中的 emulator-5554」和
// 「未运行的同名 AVD」两条幽灵。
func TestLiveAVD(t *testing.T) {
	names := listAVDs()
	if len(names) == 0 {
		t.Skip("本机没有 AVD，跳过")
	}
	t.Logf("AVD: %v", names)
	t.Logf("gpuMode=%s sdkRoot=%s emulator=%s", gpuMode(), sdkRoot(), sdkTool("emulator"))
	for _, d := range newAndroidDevice().devices() {
		if n := avdOfSerial(d.Serial); n != "" {
			t.Logf("%s ← AVD %q", d.Serial, n)
			if serialOfAVD(n) != d.Serial {
				t.Errorf("serialOfAVD(%q)=%q，要 %q", n, serialOfAVD(n), d.Serial)
			}
		}
	}
	t.Logf("已装镜像: %+v", installedImages())
	t.Logf("机型档: %d 个", len(deviceProfiles()))
}

// TestLiveAVDCreate 端到端过一遍新建：建 → 起 → 停 → 删。
// 默认跳过（会真建一台机器、吃几 GB 内存、跑好几分钟）：
//
//	cd backend && TTMUX_AVD_E2E=1 go test ./phone/ -run TestLiveAVDCreate -v -timeout 20m
//
// 只用**已下载**的系统镜像，不碰下载那条路——那条得几 GB 流量。
func TestLiveAVDCreate(t *testing.T) {
	if os.Getenv("TTMUX_AVD_E2E") == "" {
		t.Skip("要真建一台模拟器，置 TTMUX_AVD_E2E=1 才跑")
	}
	imgs := installedImages()
	if len(imgs) == 0 {
		t.Skip("本机没有已下载的系统镜像")
	}
	// 没 KVM 权限就只验「建出来」这半程：启动那半程在这台机器上必然失败，
	// 而它失败得快且话说得清（见 kvmUsable），不必拿它当断言。
	canStart := kvmUsable() == nil
	req := avdCreateReq{Name: "ttmux_e2e_probe", Pkg: imgs[0].Pkg, RAM: 2048, Disk: "3G", Start: canStart}
	if strings.Contains(req.Pkg, "android-tv") {
		req.Device, req.Width, req.Height, req.Density = "tv_1080p", 1920, 1080, 320
	}
	if err := validateCreate(req, listAVDs(), true); err != nil {
		t.Fatalf("校验就没过: %v", err)
	}
	task := newTask()
	runCreate(task, req)
	_, _, status, errMsg, _ := task.snapshot(0)
	defer func() {
		if s := serialOfAVD(req.Name); s != "" {
			_ = stopAVD(s)
			for i := 0; i < 30 && serialOfAVD(req.Name) != ""; i++ {
				time.Sleep(2 * time.Second)
			}
		}
		if err := deleteAVD(req.Name); err != nil {
			t.Errorf("删除失败（残留一台 %s 要手工清）: %v", req.Name, err)
		}
	}()
	lines, _, _, _, _ := task.snapshot(0)
	t.Logf("任务日志:\n%s", strings.Join(lines, "\n"))
	if status != "done" {
		t.Fatalf("创建失败: %s", errMsg)
	}
	if canStart {
		serial := serialOfAVD(req.Name)
		if serial == "" {
			t.Fatal("建完并启动了，却反查不到 serial")
		}
		t.Logf("已建并启动: %s → %s", req.Name, serial)
	} else {
		t.Logf("本机无 KVM 权限，只验到「建出来」：%v", kvmUsable())
	}
	// config.ini 该按我们写的来（TV 没有 dPad 就是块砖）
	b, err := os.ReadFile(filepath.Join(avdHome(), req.Name+".avd", "config.ini"))
	if err != nil {
		t.Fatalf("读 config.ini: %v", err)
	}
	for _, want := range []string{"hw.ramSize=2048", "disk.dataPartition.size=3G", "hw.keyboard=yes"} {
		if !strings.Contains(string(b), want) {
			t.Errorf("config.ini 缺 %q", want)
		}
	}
	if strings.Contains(req.Pkg, "android-tv") && !strings.Contains(string(b), "hw.dPad=yes") {
		t.Error("TV 档要有 hw.dPad=yes")
	}
}
