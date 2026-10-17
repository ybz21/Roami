// PluginRun API 的端到端测试:真 ttmux CLI + 隔离 ROAM_HOME。
// 覆盖 host-monitor 内置插件的 stats 采样,以及「命令必须属于路由里的
// 插件」的短名前缀校验(命令 ID 前缀是插件短名而非全 id,防回归)。
package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/ttmux"
)

func TestPluginRunE2E(t *testing.T) {
	if testing.Short() {
		t.Skip("short mode")
	}
	if _, err := exec.LookPath("go"); err != nil {
		t.Skip("go not available to build CLI")
	}
	tmp := t.TempDir()
	isolateTestStorage(t, tmp)

	bin := filepath.Join(tmp, "ttmux-e2e")
	root, _ := filepath.Abs("../..")
	// -buildvcs=false：从 git 钩子里跑测试时会继承 GIT_DIR，go 的 VCS 标记
	// 会因此认错仓库直接失败；这里只是造个临时二进制，版本戳没意义。
	build := exec.Command("go", "build", "-buildvcs=false", "-o", bin, "./cmd/roami")
	build.Dir = root
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build cli: %v\n%s", err, out)
	}

	gin.SetMode(gin.TestMode)
	h := New(ttmux.New(bin), "", tmp, "")
	r := gin.New()
	r.POST("/plugins/:id/run", h.PluginRun)

	call := func(id string, body map[string]any) *httptest.ResponseRecorder {
		b, _ := json.Marshal(body)
		req := httptest.NewRequest(http.MethodPost, "/plugins/"+id+"/run", bytes.NewReader(b))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		return w
	}

	// 正常路径:web 传全 id,命令是短名前缀 → 放行并返回快照
	w := call("roam.host-monitor", map[string]any{"command": "host-monitor.stats", "args": map[string]string{}})
	if w.Code != http.StatusOK {
		t.Fatalf("stats run = %d: %s", w.Code, w.Body.String())
	}
	var snap struct {
		CPU     struct{ Cores int }       `json:"cpu"`
		Memory  struct{ Total uint64 }    `json:"memory"`
		History []map[string]any          `json:"history"`
		Host    struct{ Hostname string } `json:"host"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &snap); err != nil {
		t.Fatalf("bad snapshot json: %v\n%s", err, w.Body.String())
	}
	if snap.CPU.Cores <= 0 || snap.Host.Hostname == "" || len(snap.History) == 0 {
		t.Errorf("snapshot missing fields: %s", w.Body.String())
	}
	if _, err := os.Stat("/proc/meminfo"); err == nil && snap.Memory.Total == 0 {
		t.Errorf("linux should report memory total: %s", w.Body.String())
	}

	// 越权路径:借 review-mesh 的 id 调 host-monitor 的命令 → BAD_COMMAND
	w = call("roam.review-mesh", map[string]any{"command": "host-monitor.stats"})
	if w.Code != http.StatusBadRequest {
		t.Errorf("cross-plugin run should be rejected, got %d: %s", w.Code, w.Body.String())
	}

	// 伪造 publisher:短名前缀能对上,但注册表里查无 evil.host-monitor,
	// CLI 按全 id 限定命令拒绝,不会落到短名匹配的真实所有者上
	w = call("evil.host-monitor", map[string]any{"command": "host-monitor.stats"})
	if w.Code == http.StatusOK {
		t.Errorf("forged publisher id should be rejected, got 200: %s", w.Body.String())
	}
}
