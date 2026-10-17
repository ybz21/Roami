package memthrottle

import (
	"os"
	"strings"

	"github.com/ybz21/Roami/internal/memguard"
)

// SwapRoom 回答总量闸动手前必须先问的那个问题：**回收出来的匿名页往哪儿放**。
//
// 从前没问。软限（memory.high）被当成「让内核去回收」，可它只是让内核在这个会话的
// 每一次分配上做直接回收 —— 回收得出来才叫减速，回收不出来就是干转：内核一遍遍扫
// LRU 一页也腾不出，PSI 冲高，systemd-oomd 按压力选 victim，把整条 scope
// （shell、agent、连里面跑着的模拟器）一起端掉。
//
// 2026-09-06 22:09 就是这么没的一个会话：8G swap 用掉 7.3G，zswap 关着、zram 没加载，
// 那台机器上「回收」这个动作根本没有落点。
type SwapRoom struct {
	Free       int64 // 交换区剩余字节。zram 也算 —— 对「往哪儿放」这个问题，它和磁盘 swap 同类
	Compressed bool  // 落点是压缩的（zram 交换设备 / zswap 打开）
}

// ProbeSwapRoom 读这台机器此刻的落点状况。
func ProbeSwapRoom() SwapRoom {
	return SwapRoom{Free: memguard.SwapFree(), Compressed: zramActive() || zswapOn()}
}

// zramActive 有没有启用中的 zram 交换设备。/proc/swaps 列的是**已经 swapon 的**，
// 只看 /sys/block/zram0 存在会把「建了但没挂上」误判成有。
func zramActive() bool {
	b, err := os.ReadFile("/proc/swaps")
	if err != nil {
		return false
	}
	for _, line := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(line, "/dev/zram") {
			return true
		}
	}
	return false
}

// zswapOn zswap 是不是开着（压缩缓存挡在磁盘 swap 前面）。
func zswapOn() bool {
	b, err := os.ReadFile("/sys/module/zswap/parameters/enabled")
	if err != nil {
		return false
	}
	return strings.EqualFold(strings.TrimSpace(string(b)), "Y")
}
