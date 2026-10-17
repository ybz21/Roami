package main

import "testing"

// 诊断口只允许绑回环。这条断言存在的意义是防手滑：":6060" 和 "0.0.0.0:6060" 看着
// 像「本机」，实际是对全世界开——pprof 暴露在公网既泄露内存内容，也是打垮进程的现成入口。
func TestLoopbackOnly(t *testing.T) {
	ok := []string{"127.0.0.1:6060", "localhost:6060", "[::1]:6060", "127.9.9.9:1"}
	bad := []string{":6060", "0.0.0.0:6060", "[::]:6060", "192.168.1.5:6060", "47.94.183.77:6060", "6060", ""}
	for _, a := range ok {
		if !loopbackOnly(a) {
			t.Errorf("%q 应被允许", a)
		}
	}
	for _, a := range bad {
		if loopbackOnly(a) {
			t.Errorf("%q 应被拒绝", a)
		}
	}
}
