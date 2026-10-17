// Package hostmonitor is the builtin host-machine monitoring plugin:
// 一条 stats 命令返回宿主机 CPU/GPU/内存/磁盘/网络快照 + 近期历史,
// Web 端监控面板轮询它画仪表盘(设计对应 docs/design/plugin/ 的
// commands 贡献点;插件零前端,面板由宿主 Web 按插件 id 挂载)。
//
// 采样直接读本机 /proc 与 nvidia-smi(插件进程即宿主进程,不经 roam/*
// 平台 API,因此轮询不会刷审计日志)。plugin run 每次调用都是一个短命
// 子进程,跨调用状态(CPU/网络计数器、历史环形缓冲)持久化在宿主注入的
// StorageDir 里,速率按「本次 - 上次」计数器差分得出。
package hostmonitor

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"

	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

const (
	historyMax    = 240              // 历史点数上限(3s 轮询 ≈ 12 分钟)
	counterMaxAge = 10 * time.Minute // 计数器过期视为无效(避免跨重启差分出负数)
)

// Activate registers the plugin's commands (sdk.Serve 的入口).
func Activate(ctx *sdk.Ctx) sdk.Plugin {
	return sdk.Plugin{
		Commands: map[string]sdk.CommandHandler{
			"stats":      stats,
			"swap-clear": swapClear,
			// 后台任务本体:由 swap-clear 起的脱离子进程调用,同步跑完 swapoff+swapon
			"swap-cycle": swapCycle,
		},
	}
}

// Snapshot is one full readout, the stats command's return value.
type Snapshot struct {
	Time    string       `json:"time"`
	Host    HostInfo     `json:"host"`
	CPU     CPUStat      `json:"cpu"`
	Memory  MemStat      `json:"memory"`
	Disks   []DiskStat   `json:"disks"`
	GPUs    []GPUStat    `json:"gpus"`
	Network NetStat      `json:"network"`
	History []HistoryDot `json:"history"`
}

// HostInfo is the static-ish header row of the dashboard.
type HostInfo struct {
	Hostname  string  `json:"hostname"`
	OS        string  `json:"os,omitempty"`
	Kernel    string  `json:"kernel,omitempty"`
	Arch      string  `json:"arch,omitempty"`
	UptimeSec int64   `json:"uptimeSec,omitempty"`
	Load1     float64 `json:"load1"`
	Load5     float64 `json:"load5"`
	Load15    float64 `json:"load15"`
}

// CPUStat carries overall + per-core usage percent over the sampling window.
type CPUStat struct {
	Model        string    `json:"model,omitempty"`
	Cores        int       `json:"cores"`
	UsagePercent float64   `json:"usagePercent"`
	PerCore      []float64 `json:"perCore,omitempty"`
	TempC        float64   `json:"tempC,omitempty"` // 0 = 未知
}

// MemStat is in bytes; Available 语义同 /proc/meminfo MemAvailable。
type MemStat struct {
	Total        uint64  `json:"total"`
	Used         uint64  `json:"used"`
	Available    uint64  `json:"available"`
	UsagePercent float64 `json:"usagePercent"`
	SwapTotal    uint64  `json:"swapTotal"`
	SwapUsed     uint64  `json:"swapUsed"`
}

// DiskStat is one real mounted filesystem (bytes).
type DiskStat struct {
	Device       string  `json:"device"`
	Mount        string  `json:"mount"`
	FSType       string  `json:"fsType"`
	Total        uint64  `json:"total"`
	Used         uint64  `json:"used"`
	Free         uint64  `json:"free"`
	UsagePercent float64 `json:"usagePercent"`
}

// GPUStat is one GPU as reported by nvidia-smi.
type GPUStat struct {
	Index        int     `json:"index"`
	Name         string  `json:"name"`
	UtilPercent  float64 `json:"utilPercent"`
	MemUsed      uint64  `json:"memUsed"`  // bytes
	MemTotal     uint64  `json:"memTotal"` // bytes
	TempC        float64 `json:"tempC"`
	PowerW       float64 `json:"powerW"`
	PowerLimitW  float64 `json:"powerLimitW"`
	FanPercent   float64 `json:"fanPercent"`
	MemUsagePerc float64 `json:"memUsagePercent"`
}

// NetStat is host-wide throughput over the sampling window (bytes/s).
type NetStat struct {
	RxBytesPerSec float64 `json:"rxBytesPerSec"`
	TxBytesPerSec float64 `json:"txBytesPerSec"`
}

// HistoryDot is one compact point for the dashboard sparklines.
type HistoryDot struct {
	T   int64   `json:"t"` // unix 秒
	CPU float64 `json:"cpu"`
	Mem float64 `json:"mem"`
	GPU float64 `json:"gpu"` // 多卡取最大利用率;无卡为 0
	Rx  float64 `json:"rx"`  // bytes/s
	Tx  float64 `json:"tx"`
}

// counters is the persisted previous readout used for rate deltas.
type counters struct {
	Time    int64      `json:"time"` // unix 毫秒
	CPU     cpuTicks   `json:"cpu"`
	PerCore []cpuTicks `json:"perCore,omitempty"`
	NetRx   uint64     `json:"netRx"`
	NetTx   uint64     `json:"netTx"`
}

// stats 命令:采一次全量快照。CPU/网络速率优先用 StorageDir 里上一次的
// 计数器差分(窗口=轮询间隔,更平滑);无上次记录时退化为进程内短窗采样。
func stats(ctx *sdk.Ctx, args map[string]string) (any, error) {
	now := time.Now()
	snap := Snapshot{Time: now.Format(time.RFC3339)}

	if ctx.StorageDir != "" {
		os.MkdirAll(ctx.StorageDir, 0o755) // 宿主只注入路径不建目录
	}
	prev := loadCounters(ctx.StorageDir)
	cur, sampled := collect(prev, now)
	snap.Host = cur.Host
	snap.CPU = cur.CPU
	snap.Memory = cur.Memory
	snap.Disks = cur.Disks
	snap.Network = cur.Network
	snap.GPUs = readGPUs()

	saveCounters(ctx.StorageDir, sampled)
	snap.History = appendHistory(ctx.StorageDir, HistoryDot{
		T:   now.Unix(),
		CPU: snap.CPU.UsagePercent,
		Mem: snap.Memory.UsagePercent,
		GPU: maxGPUUtil(snap.GPUs),
		Rx:  snap.Network.RxBytesPerSec,
		Tx:  snap.Network.TxBytesPerSec,
	})
	return snap, nil
}

func maxGPUUtil(gpus []GPUStat) float64 {
	m := 0.0
	for _, g := range gpus {
		if g.UtilPercent > m {
			m = g.UtilPercent
		}
	}
	return m
}

// ── StorageDir 持久化(短命进程的跨调用状态) ──

func loadCounters(dir string) *counters {
	if dir == "" {
		return nil
	}
	b, err := os.ReadFile(filepath.Join(dir, "counters.json"))
	if err != nil {
		return nil
	}
	var c counters
	if json.Unmarshal(b, &c) != nil {
		return nil
	}
	if time.Since(time.UnixMilli(c.Time)) > counterMaxAge {
		return nil // 太久之前的计数器(或时钟回拨),丢弃
	}
	return &c
}

func saveCounters(dir string, c *counters) {
	if dir == "" || c == nil {
		return
	}
	b, err := json.Marshal(c)
	if err != nil {
		return
	}
	os.WriteFile(filepath.Join(dir, "counters.json"), b, 0o644)
}

// appendHistory 把本次点追加进环形历史并返回全量(并发轮询的竞态最多丢
// 一个点,可接受)。
func appendHistory(dir string, dot HistoryDot) []HistoryDot {
	if dir == "" {
		return []HistoryDot{dot}
	}
	path := filepath.Join(dir, "history.json")
	var hist []HistoryDot
	if b, err := os.ReadFile(path); err == nil {
		json.Unmarshal(b, &hist)
	}
	// 跨重启/久未轮询的陈旧段直接清掉,图上不连一条跨小时的假线
	if n := len(hist); n > 0 && dot.T-hist[n-1].T > 600 {
		hist = nil
	}
	hist = append(hist, dot)
	if len(hist) > historyMax {
		hist = hist[len(hist)-historyMax:]
	}
	if b, err := json.Marshal(hist); err == nil {
		os.WriteFile(path, b, 0o644)
	}
	return hist
}
