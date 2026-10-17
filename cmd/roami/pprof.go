package main

import (
	"log"
	"net"
	"net/http"
	"net/http/pprof"
	"strings"
	"time"
)

// startPprof 按需开一个**只绑回环**的诊断口：ROAM_PPROF=127.0.0.1:6060。
//
// 为什么要有这个：2026-08-10 中心在一台 1.6G 内存的机器上涨到 511MB RSS、106% CPU
// 把自己压死——端口能连、HTTP 不响应、accept 队列积到 586。当时手上只有 ps 和日志，
// 而 RSS 与线程数说明不了是谁在堆：Go 的 goroutine 复用少量线程，12 个线程照样挂得住
// 上万个 goroutine。于是只能重启了事，根因带不走。有这个口就能当场取证：
//
//	curl -s localhost:6060/debug/pprof/heap > heap.out
//	curl -s 'localhost:6060/debug/pprof/goroutine?debug=1' | head -60
//	go tool pprof -top heap.out
//
// 默认关闭，且**拒绝非回环地址**：pprof 挂到公网既是信息泄露（源码路径、内存里的内容），
// 也是现成的打垮入口（一个 profile 请求就能占满 CPU）。要远程看就 ssh 端口转发。
func startPprof(addr string) {
	if !loopbackOnly(addr) {
		log.Printf("ROAM_PPROF=%s 被拒：诊断口只允许绑回环（127.0.0.1 / [::1]），远程请用 ssh -L 转发", addr)
		return
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/debug/pprof/", pprof.Index)
	mux.HandleFunc("/debug/pprof/cmdline", pprof.Cmdline)
	mux.HandleFunc("/debug/pprof/profile", pprof.Profile)
	mux.HandleFunc("/debug/pprof/symbol", pprof.Symbol)
	mux.HandleFunc("/debug/pprof/trace", pprof.Trace)

	srv := &http.Server{
		Addr:    addr,
		Handler: mux,
		// profile / trace 本来就要跑满 30 秒，读超时得给够，否则抓不完就被掐断
		ReadHeaderTimeout: 5 * time.Second,
		WriteTimeout:      2 * time.Minute,
	}
	go func() {
		log.Printf("诊断口（pprof）监听 http://%s/debug/pprof/", addr)
		if err := srv.ListenAndServe(); err != nil {
			log.Printf("诊断口退出: %v", err)
		}
	}()
}

// loopbackOnly 判断监听地址是否只对本机可见。
// 空 host（":6060"）等于 0.0.0.0，一律拒绝——这正是最容易手滑写出来的那种。
func loopbackOnly(addr string) bool {
	host, _, err := net.SplitHostPort(addr)
	if err != nil {
		return false
	}
	host = strings.Trim(host, "[]")
	if host == "" {
		return false
	}
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}
