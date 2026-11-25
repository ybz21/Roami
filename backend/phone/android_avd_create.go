// android_avd_create.go：从 Web 端新建/删除本机模拟器。
//
// 与 android_avd.go 分工：那边管已有 AVD 的发现与起停，这边管「从零建一台」——
// 机型档与系统镜像目录、下载镜像、avdmanager 创建、改写 config.ini、删除。
//
// 为什么要有任务与 SSE：新建常常要先下载一个 1.5–2.5G 的系统镜像，几分钟到几十分钟，
// 远超任何 HTTP 超时，用户还会关抽屉、切页面。所以 POST 只发号，进度另走 SSE，任务活在后端。
package phone

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/ybz21/Roami/internal/procctl"
)

// ── 目录：机型档 + 系统镜像 ──

// avdDeviceProfile 是 `avdmanager list device` 里的一个机型档。Tag 为空即普通手机档。
type avdDeviceProfile struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	OEM  string `json:"oem,omitempty"`
	Tag  string `json:"tag,omitempty"` // android-tv / android-wear / android-automotive…
}

// avdImage 是一个系统镜像包。Variant/ABI 原样给前端，标签由 i18n 拼——
// sdkmanager 的 Description 是英文，直接显示就把英文漏进了界面。
type avdImage struct {
	Pkg       string `json:"pkg"` // system-images;android-36;android-tv;x86_64
	API       string `json:"api"` // 36 / 35-ext14
	Variant   string `json:"variant"`
	ABI       string `json:"abi"`
	Installed bool   `json:"installed"`
}

// hostABI：只列宿主架构对得上的镜像。x86 机器上跑 arm64 镜像要全量翻译，慢到没法用。
func hostABI() string {
	if runtime.GOARCH == "arm64" {
		return "arm64-v8a"
	}
	return "x86_64"
}

// avdHome 是 AVD 的落地目录（config.ini 在这里）。
func avdHome() string {
	if v := strings.TrimSpace(os.Getenv("ANDROID_AVD_HOME")); v != "" {
		return v
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".android", "avd")
}

var devProfileRe = regexp.MustCompile(`^id:\s*\d+\s+or\s+"([^"]+)"`)

// parseDeviceProfiles 解析 `avdmanager list device`：每档以 id 行起头，后面跟 Name/OEM/Tag。
func parseDeviceProfiles(out string) []avdDeviceProfile {
	var list []avdDeviceProfile
	for _, ln := range strings.Split(out, "\n") {
		ln = strings.TrimRight(ln, "\r")
		t := strings.TrimSpace(ln)
		if m := devProfileRe.FindStringSubmatch(t); m != nil {
			list = append(list, avdDeviceProfile{ID: m[1], Name: m[1]})
			continue
		}
		if len(list) == 0 {
			continue
		}
		cur := &list[len(list)-1]
		k, v, ok := strings.Cut(t, ":")
		if !ok {
			continue
		}
		v = strings.TrimSpace(v)
		switch strings.TrimSpace(k) {
		case "Name":
			cur.Name = v
		case "OEM":
			cur.OEM = v
		case "Tag":
			cur.Tag = v
		}
	}
	return list
}

func deviceProfiles() []avdDeviceProfile {
	bin := sdkTool("avdmanager")
	if bin == "" {
		return nil
	}
	out, err := runCmd(60*time.Second, bin, "list", "device")
	if err != nil {
		return nil
	}
	return parseDeviceProfiles(string(out))
}

// parseImagePkg 拆包名：system-images;android-36;android-tv;x86_64。
func parseImagePkg(pkg string) (avdImage, bool) {
	p := strings.Split(strings.TrimSpace(pkg), ";")
	if len(p) != 4 || p[0] != "system-images" {
		return avdImage{}, false
	}
	return avdImage{Pkg: pkg, API: strings.TrimPrefix(p[1], "android-"), Variant: p[2], ABI: p[3]}, true
}

// installedImages 直接扫盘：$SDK/system-images/<api>/<variant>/<abi>。
// 不走 sdkmanager——它每次都要拉远端仓库（实测几十秒），而「已经装了哪些」本地就有答案。
func installedImages() []avdImage {
	root := sdkRoot()
	if root == "" {
		return nil
	}
	dirs, _ := filepath.Glob(filepath.Join(root, "system-images", "*", "*", "*"))
	var list []avdImage
	for _, d := range dirs {
		if st, err := os.Stat(d); err != nil || !st.IsDir() {
			continue
		}
		rel, err := filepath.Rel(filepath.Join(root, "system-images"), d)
		if err != nil {
			continue
		}
		parts := strings.Split(filepath.ToSlash(rel), "/")
		if len(parts) != 3 {
			continue
		}
		img, ok := parseImagePkg("system-images;" + strings.Join(parts, ";"))
		if !ok {
			continue
		}
		img.Installed = true
		list = append(list, img)
	}
	return list
}

// remoteImages 是可下载的镜像目录（sdkmanager --list），缓存 10 分钟：那趟远端拉取要几十秒。
var imgCache struct {
	mu   sync.Mutex
	at   time.Time
	list []avdImage
}

func remoteImages(force bool) []avdImage {
	imgCache.mu.Lock()
	if !force && time.Since(imgCache.at) < 10*time.Minute && imgCache.list != nil {
		defer imgCache.mu.Unlock()
		return imgCache.list
	}
	imgCache.mu.Unlock()

	bin := sdkTool("sdkmanager")
	if bin == "" {
		return nil
	}
	out, err := runCmd(180*time.Second, bin, "--list")
	if err != nil && len(out) == 0 {
		return nil
	}
	seen := map[string]bool{}
	var list []avdImage
	for _, ln := range strings.Split(string(out), "\n") {
		// 形如 "  system-images;android-36;android-tv;x86_64 | 4 | Android TV … | …"
		head, _, ok := strings.Cut(ln, "|")
		if !ok {
			continue
		}
		img, ok := parseImagePkg(strings.TrimSpace(head))
		if !ok || seen[img.Pkg] || img.ABI != hostABI() {
			continue
		}
		seen[img.Pkg] = true
		list = append(list, img)
	}
	imgCache.mu.Lock()
	imgCache.at, imgCache.list = time.Now(), list
	imgCache.mu.Unlock()
	return list
}

// avdCatalog 合并两边：本地扫出来的标 installed，远端目录补齐可下载的。
func avdCatalog(withRemote bool) []avdImage {
	byPkg := map[string]avdImage{}
	var order []string
	for _, i := range installedImages() {
		if _, ok := byPkg[i.Pkg]; !ok {
			order = append(order, i.Pkg)
		}
		byPkg[i.Pkg] = i
	}
	if withRemote {
		for _, i := range remoteImages(false) {
			if _, ok := byPkg[i.Pkg]; ok {
				continue
			}
			order = append(order, i.Pkg)
			byPkg[i.Pkg] = i
		}
	}
	list := make([]avdImage, 0, len(order))
	for _, p := range order {
		list = append(list, byPkg[p])
	}
	return list
}

// ── 创建任务 ──

type avdTask struct {
	ID string `json:"id"`

	mu     sync.Mutex
	log    []string
	pct    int
	status string // running | done | error
	errMsg string
	wait   chan struct{} // 每次更新后 close 再换新的：SSE 端就 select 在它上面，不必轮询
}

var pctRe = regexp.MustCompile(`(\d{1,3})\s*%`)

func (t *avdTask) push(line string) {
	line = strings.TrimSpace(line)
	if line == "" {
		return
	}
	t.mu.Lock()
	t.log = append(t.log, line)
	if len(t.log) > 400 { // 只留尾部：下载进度行成千上万
		t.log = t.log[len(t.log)-400:]
	}
	if m := pctRe.FindStringSubmatch(line); m != nil {
		if v, err := strconv.Atoi(m[1]); err == nil && v >= 0 && v <= 100 {
			t.pct = v
		}
	}
	close(t.wait)
	t.wait = make(chan struct{})
	t.mu.Unlock()
}

func (t *avdTask) finish(err error) {
	t.mu.Lock()
	if err != nil {
		t.status, t.errMsg = "error", err.Error()
	} else {
		t.status, t.pct = "done", 100
	}
	close(t.wait)
	t.wait = make(chan struct{})
	t.mu.Unlock()
}

// snapshot 取从 from 行起的增量 + 状态 + 下一次更新的信号。
func (t *avdTask) snapshot(from int) (lines []string, pct int, status, errMsg string, wait chan struct{}) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if from < len(t.log) {
		lines = append(lines, t.log[from:]...)
	}
	return lines, t.pct, t.status, t.errMsg, t.wait
}

var tasks struct {
	mu sync.Mutex
	m  map[string]*avdTask
	n  int
}

func newTask() *avdTask {
	tasks.mu.Lock()
	defer tasks.mu.Unlock()
	if tasks.m == nil {
		tasks.m = map[string]*avdTask{}
	}
	tasks.n++
	t := &avdTask{ID: fmt.Sprintf("avd-%d", tasks.n), status: "running", wait: make(chan struct{})}
	tasks.m[t.ID] = t
	// 只留最近 10 个任务，别让日志无限堆着
	if len(tasks.m) > 10 {
		oldest := ""
		for id, v := range tasks.m {
			if v.status == "running" {
				continue
			}
			if oldest == "" || id < oldest {
				oldest = id
			}
		}
		if oldest != "" {
			delete(tasks.m, oldest)
		}
	}
	return t
}

func getTask(id string) *avdTask {
	tasks.mu.Lock()
	defer tasks.mu.Unlock()
	return tasks.m[id]
}

// yesReader 无限吐 "y\n"，等价于 shell 的 `yes`：sdkmanager 接受许可时会反复问。
type yesReader struct{}

func (yesReader) Read(p []byte) (int, error) {
	n := 0
	for n+2 <= len(p) {
		p[n], p[n+1] = 'y', '\n'
		n += 2
	}
	if n == 0 {
		return 0, nil
	}
	return n, nil
}

// scanLinesCR 按 \n 或 \r 断行：sdkmanager 的进度条用 \r 原地刷新，只认 \n 会攒成一行巨串。
func scanLinesCR(data []byte, atEOF bool) (int, []byte, error) {
	for i, b := range data {
		if b == '\n' || b == '\r' {
			return i + 1, data[:i], nil
		}
	}
	if atEOF && len(data) > 0 {
		return len(data), data, nil
	}
	return 0, nil, nil
}

// streamCmd 跑命令并逐行回调（stdout+stderr 合流），超时杀整个进程组。
// stdin 传 nil 表示不喂输入；sdkmanager/avdmanager 的交互式追问靠它答。
func streamCmd(timeout time.Duration, stdin interface{ Read([]byte) (int, error) },
	onLine func(string), name string, args ...string) error {
	cmd := exec.Command(name, args...)
	procctl.SetProcessGroup(cmd)
	if stdin != nil {
		cmd.Stdin = stdin
	}
	pr, pw, err := os.Pipe()
	if err != nil {
		return err
	}
	cmd.Stdout, cmd.Stderr = pw, pw
	if err := cmd.Start(); err != nil {
		pw.Close()
		pr.Close()
		return fmt.Errorf("%s 启动失败: %w", filepath.Base(name), err)
	}
	pw.Close() // 父进程这份必须关，否则子进程退出后 scanner 不会 EOF
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	timer := time.AfterFunc(timeout, func() {
		procctl.TerminateGroup(cmd.Process, 2*time.Second)
	})
	defer timer.Stop()
	sc := bufio.NewScanner(pr)
	sc.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	sc.Split(scanLinesCR)
	last := ""
	for sc.Scan() {
		if ln := strings.TrimSpace(sc.Text()); ln != "" && ln != last {
			last = ln
			onLine(ln)
		}
	}
	pr.Close()
	return <-done
}

var avdNameRe = regexp.MustCompile(`^[A-Za-z0-9._-]+$`)

// avdCreateReq 是新建一台模拟器要的全部输入。
type avdCreateReq struct {
	Name    string `json:"name"`
	Pkg     string `json:"pkg"`              // system-images;…
	Device  string `json:"device,omitempty"` // 机型档 id
	RAM     int    `json:"ram,omitempty"`    // MB
	Disk    string `json:"disk,omitempty"`   // 数据分区，如 6G
	Width   int    `json:"width,omitempty"`
	Height  int    `json:"height,omitempty"`
	Density int    `json:"density,omitempty"`
	// AcceptLicense 是用户在界面上按下的「接受 Google Android SDK 许可」。
	// 缺镜像时必须为真才动手下载——许可不能替用户默默同意。
	AcceptLicense bool `json:"acceptLicense,omitempty"`
	Start         bool `json:"start,omitempty"` // 建完立即启动
}

// validateCreate 只做纯校验，便于测试。
func validateCreate(r avdCreateReq, existing []string, installed bool) error {
	if !avdNameRe.MatchString(r.Name) {
		return errors.New("名称只能用字母/数字/点/下划线/减号（avdmanager 不收空格和中文）")
	}
	for _, n := range existing {
		if n == r.Name {
			// 绝不 --force：那会连同已有 AVD 的应用与数据一起覆盖掉。
			return fmt.Errorf("已有同名模拟器 %s，换个名字", r.Name)
		}
	}
	if _, ok := parseImagePkg(r.Pkg); !ok {
		return errors.New("系统镜像包名不合法")
	}
	if !installed && !r.AcceptLicense {
		return errors.New("该镜像尚未下载，需先接受 Google Android SDK 许可")
	}
	return nil
}

func imageInstalled(pkg string) bool {
	for _, i := range installedImages() {
		if i.Pkg == pkg {
			return true
		}
	}
	return false
}

// runCreate 是任务主体：下载镜像 → 建 AVD → 改 config.ini →（可选）启动。
func runCreate(t *avdTask, r avdCreateReq) {
	sdkmanager, avdmanager := sdkTool("sdkmanager"), sdkTool("avdmanager")
	if avdmanager == "" {
		t.finish(errors.New("未找到 avdmanager（装 Android SDK 的 cmdline-tools）"))
		return
	}
	if !imageInstalled(r.Pkg) {
		if sdkmanager == "" {
			t.finish(errors.New("未找到 sdkmanager（装 Android SDK 的 cmdline-tools）"))
			return
		}
		t.push("接受 SDK 许可…")
		if err := streamCmd(5*time.Minute, yesReader{}, t.push, sdkmanager, "--licenses"); err != nil {
			t.push("许可步骤返回：" + err.Error()) // 已全部接受时它也会非零退出，不作为失败
		}
		t.push("下载系统镜像 " + r.Pkg + "（几百 MB 到数 GB，慢）…")
		if err := streamCmd(2*time.Hour, yesReader{}, t.push, sdkmanager, r.Pkg); err != nil {
			t.finish(fmt.Errorf("下载系统镜像失败: %w", err))
			return
		}
	}
	t.push("创建 AVD " + r.Name + "…")
	args := []string{"create", "avd", "-n", r.Name, "-k", r.Pkg}
	if r.Device != "" {
		args = append(args, "-d", r.Device)
	}
	// stdin 喂 "no"：avdmanager 会追问「要不要自定义硬件档」，没人应答就卡死。
	if err := streamCmd(5*time.Minute, strings.NewReader("no\n"), t.push, avdmanager, args...); err != nil {
		t.finish(fmt.Errorf("创建失败: %w", err))
		return
	}
	if err := tuneAVDConfig(r); err != nil {
		t.push("调整 config.ini 失败（不致命）：" + err.Error())
	}
	if r.Start {
		t.push("启动模拟器…")
		if _, err := startAVD(r.Name, false); err != nil {
			t.finish(err)
			return
		}
	}
	t.push("完成")
	t.finish(nil)
}

// tuneAVDConfig 改写新建 AVD 的 config.ini。
//
// 这步不能省：avdmanager 建出来的 TV 档未必带方向键，而没有 D-pad 的电视就是块砖——
// 电视没有触摸屏，焦点走位是唯一的交互方式。
//
// 分辨率则**只在调用方给了才改**：选了机型档时那一档自己写的才对（tv_4k 是
// 3840x2160@640），这里再盖一层就把 4K 按回了 1080p。调用方只在没选档时兜一个值。
func tuneAVDConfig(r avdCreateReq) error {
	p := filepath.Join(avdHome(), r.Name+".avd", "config.ini")
	b, err := os.ReadFile(p)
	if err != nil {
		return err
	}
	kv := map[string]string{}
	var order []string
	for _, ln := range strings.Split(string(b), "\n") {
		k, v, ok := strings.Cut(strings.TrimRight(ln, "\r"), "=")
		if !ok {
			continue
		}
		if _, dup := kv[k]; !dup {
			order = append(order, k)
		}
		kv[k] = v
	}
	set := func(k, v string) {
		if _, ok := kv[k]; !ok {
			order = append(order, k)
		}
		kv[k] = v
	}
	if r.RAM > 0 {
		set("hw.ramSize", strconv.Itoa(r.RAM))
	}
	if r.Disk != "" {
		set("disk.dataPartition.size", r.Disk)
	}
	if r.Width > 0 && r.Height > 0 {
		set("hw.lcd.width", strconv.Itoa(r.Width))
		set("hw.lcd.height", strconv.Itoa(r.Height))
	}
	if r.Density > 0 {
		set("hw.lcd.density", strconv.Itoa(r.Density))
	}
	set("hw.keyboard", "yes")
	if strings.Contains(r.Pkg, "android-tv") {
		set("hw.dPad", "yes")
	}
	set("hw.gpu.enabled", "yes")
	set("hw.gpu.mode", gpuMode())
	var sb strings.Builder
	for _, k := range order {
		sb.WriteString(k + "=" + kv[k] + "\n")
	}
	return os.WriteFile(p, []byte(sb.String()), 0o644)
}

// deleteAVD 删除一台模拟器。破坏性：连同 ~/.android/avd/<名>.avd 里的应用与数据一起没。
// 运行中的一律拒绝——不做「帮你先停再删」这种贴心，停机是用户该自己拍的板。
func deleteAVD(name string) error {
	if name == "" {
		return errors.New("缺少 AVD 名")
	}
	if s := serialOfAVD(name); s != "" {
		return fmt.Errorf("模拟器 %s 正在运行（%s），请先停止再删除", name, s)
	}
	bin := sdkTool("avdmanager")
	if bin == "" {
		return errors.New("未找到 avdmanager（装 Android SDK 的 cmdline-tools）")
	}
	out, err := runCmd(60*time.Second, bin, "delete", "avd", "-n", name)
	if err != nil {
		return fmt.Errorf("%s", strings.TrimSpace(string(out))+" "+err.Error())
	}
	return nil
}
