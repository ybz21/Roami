// Chrome 启动配置：屏幕尺寸/全屏/缩放/profile(data-dir)/可执行路径，持久化到
// <dataDir>/browser-config.json，由 Settings 页管理。生效优先级：UI 存的值 > 环境变量 > 默认。
// 不走 env 页（那套是 push 给 shell 会话的，影响不到后端进程自己的 ensureChrome）。
package browser

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"github.com/gin-gonic/gin"
)

// Config 是可在 UI 里调的 Chrome 启动项。字符串空 / Fullscreen 为 nil = 未设，回落到 env/默认。
type Config struct {
	Headless    string `json:"headless"`   // "auto"(按有无显示器自动) | "on"(强制无头) | "off"(强制有头)
	WindowSize  string `json:"windowSize"` // headless 初始窗口，如 "1920,1080"
	Fullscreen  *bool  `json:"fullscreen"` // headful 是否全屏启动(--start-fullscreen)
	Scale       string `json:"scale"`      // --force-device-scale-factor
	Profile     string `json:"profile"`    // --user-data-dir（用户数据目录）
	AutoRecover *bool  `json:"autoRecover"`
	Bin         string `json:"bin"` // chrome 可执行路径（空=自动探测）
}

var cfgStore struct {
	mu       sync.Mutex
	file     string // 空 = 未初始化（未配 dataDir），此时只用 env/默认
	portFile string // 自动选择的 CDP 端口记录文件
}

// InitConfig 设定配置文件路径，由 server.New 用 dataDir 调一次；并恢复上次记录的 CDP 端口。
func InitConfig(dataDir string) {
	if dataDir == "" {
		return
	}
	_ = os.MkdirAll(dataDir, 0o755)
	cfgStore.mu.Lock()
	cfgStore.file = filepath.Join(dataDir, "browser-config.json")
	cfgStore.portFile = filepath.Join(dataDir, "browser-cdp-port")
	cfgStore.mu.Unlock()
	// 恢复上次用的端口：重启后端后优先在该端口找仍存活的 Chrome（attach 而非另起）。
	if !cdpFixed {
		if p := recordedPort(); p > 0 {
			setCDPAddress("http://127.0.0.1:" + strconv.Itoa(p))
		}
	}
}

// recordPort / recordedPort 持久化自动选择的 CDP 端口，重启复用，避免反复换端口开多个 Chrome。
func recordPort(port int) {
	cfgStore.mu.Lock()
	f := cfgStore.portFile
	cfgStore.mu.Unlock()
	if f == "" {
		return
	}
	_ = os.WriteFile(f, []byte(strconv.Itoa(port)), 0o600)
}

func recordedPort() int {
	cfgStore.mu.Lock()
	f := cfgStore.portFile
	cfgStore.mu.Unlock()
	if f == "" {
		return 0
	}
	b, err := os.ReadFile(f)
	if err != nil {
		return 0
	}
	n, _ := strconv.Atoi(strings.TrimSpace(string(b)))
	return n
}

// loadConfig 读取持久化的原始配置（未设字段保持空/nil）；文件不存在或未初始化时返回零值。
func loadConfig() Config {
	cfgStore.mu.Lock()
	f := cfgStore.file
	cfgStore.mu.Unlock()
	var c Config
	if f == "" {
		return c
	}
	if b, err := os.ReadFile(f); err == nil {
		_ = json.Unmarshal(b, &c)
	}
	return c
}

// saveConfig 原子写回。
func saveConfig(c Config) error {
	cfgStore.mu.Lock()
	defer cfgStore.mu.Unlock()
	f := cfgStore.file
	if f == "" {
		return os.ErrInvalid
	}
	b, _ := json.MarshalIndent(c, "", "  ")
	tmp := f + ".tmp"
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, f)
}

// normalizeHeadless 把模式收敛到 auto/on/off（无法识别返回空 = 未设，交给 pick 回落）。
// 配置文件是手可以改的，历史上也出现过 "new"（照着 --headless=new 写）这种野值：不收敛的话
// Settings 的分段控件选不中任何一项，而 ensureChrome 把它当成「非 off」照样按无头跑
// —— 界面和实际就此对不上，还看不出为什么。
func normalizeHeadless(v string) string {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "auto":
		return "auto"
	case "on", "new", "true", "1":
		return "on"
	case "off", "false", "0":
		return "off"
	}
	return ""
}

func pick(stored, env, def string) string {
	if stored != "" {
		return stored
	}
	if env != "" {
		return env
	}
	return def
}

// effectiveConfig 把「存的值 > env > 默认」解析成全部字段都有值的生效配置，供 ensureChrome 与 UI 回显共用。
func effectiveConfig() Config {
	c := loadConfig()
	fs := true // 默认全屏
	if c.Fullscreen != nil {
		fs = *c.Fullscreen
	} else if os.Getenv("TTMUX_CHROME_FULLSCREEN") == "0" {
		fs = false
	}
	recover := true
	if c.AutoRecover != nil {
		recover = *c.AutoRecover
	}
	return Config{
		AutoRecover: &recover,
		Headless:    pick(normalizeHeadless(c.Headless), "", "auto"),
		WindowSize:  pick(c.WindowSize, os.Getenv("TTMUX_CHROME_WINDOW"), "1920,1080"),
		Fullscreen:  &fs,
		Scale:       pick(c.Scale, os.Getenv("TTMUX_CHROME_SCALE"), "2"),
		Profile:     pick(c.Profile, os.Getenv("TTMUX_CHROME_PROFILE"), "/tmp/ttmux-chrome"),
		Bin:         pick(c.Bin, os.Getenv("CHROME_BIN"), ""),
	}
}

// GetConfig 返回当前生效配置（已填默认值，便于 UI 直接展示）。
func GetConfig(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"data": effectiveConfig()})
}

// Health 报告 Chrome 当前是否可用、CDP 地址、最近一次启动失败原因，供前端在「连不上」时显示为什么。
func Health(c *gin.Context) {
	statusMu.Lock()
	e := lastErr
	statusMu.Unlock()
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"alive": alive(), "cdp": cdpAddress(), "error": e, "restarting": restarting.Load(), "canRestart": localCDP(), "autoRecover": *effectiveConfig().AutoRecover}})
}

// SetConfig 整体覆盖保存配置（不立即重启 Chrome；调 /browser/relaunch 才换上新参数）。
func SetConfig(c *gin.Context) {
	cfgStore.mu.Lock()
	initialized := cfgStore.file != ""
	cfgStore.mu.Unlock()
	if !initialized {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "NO_STORE"}})
		return
	}
	var in Config
	if err := c.ShouldBindJSON(&in); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	in.Headless = normalizeHeadless(in.Headless) // 落盘的就是干净值，chrome CLI 也读同一份文件
	if err := saveConfig(in); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "WRITE_ERROR", "message": err.Error()}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
}

// Relaunch also adopts a local Chrome launched by the CLI or an earlier server.
func Relaunch(c *gin.Context) {
	result, err := restartChrome(nil)
	if err != nil {
		setLastErr(err.Error())
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{"code": "RELAUNCH_FAILED", "message": err.Error()}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": result})
}
