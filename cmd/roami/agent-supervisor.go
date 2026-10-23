package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/ybz21/Roami/internal/agentruntime"
)

func agentEnvironment() []string {
	var result []string
	for _, value := range os.Environ() {
		key, _, _ := strings.Cut(value, "=")
		switch key {
		case "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "ROAMI_AGENT_CLI":
			continue
		}
		result = append(result, value)
	}
	return result
}

func agentReady(socket string) bool {
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", "http://roami-agent/v1/status", nil)
	req.Header.Set("X-Roami-Owner", "local")
	transport := agentruntime.Transport(socket)
	defer transport.CloseIdleConnections()
	response, err := (&http.Client{Transport: transport}).Do(req)
	if err != nil {
		return false
	}
	defer response.Body.Close()
	return response.StatusCode == http.StatusOK
}

// The pipe belongs only to this web process; EOF also shuts down Python after a crash.
func startAgentSupervisor() (func(), error) {
	dir, err := agentRuntimeDir("")
	if err != nil {
		return func() {}, err
	}
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		return func() {}, err
	}
	if agentReady(paths.Socket) {
		return func() {}, nil // A manually managed runtime retains its own lifecycle.
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	ready := make(chan error, 1)
	var first sync.Once
	report := func(err error) { first.Do(func() { ready <- err }) }
	go func() {
		defer close(done)
		delay := time.Second
		for ctx.Err() == nil {
			if err := initializeAgent(dir); err != nil {
				log.Printf("智能体初始化失败，稍后重试: %v", err)
			} else {
				cmd, err := agentPythonCommand(dir, paths, false)
				if err != nil {
					report(err)
					return
				}
				reader, writer, err := os.Pipe()
				if err != nil {
					report(err)
					return
				}
				cmd.ExtraFiles = []*os.File{reader}
				cmd.Args = append(cmd.Args, "--parent-fd", "3")
				startedAt := time.Now()
				err = cmd.Start()
				reader.Close()
				if err != nil {
					writer.Close()
					report(err)
					return
				}
				exited := make(chan error, 1)
				go func() { exited <- cmd.Wait() }()
				started := false
				deadline := time.NewTimer(20 * time.Second)
				ticker := time.NewTicker(100 * time.Millisecond)
			running:
				for {
					select {
					case <-ctx.Done():
						writer.Close()
						select {
						case <-exited:
						case <-time.After(10 * time.Second):
							_ = cmd.Process.Signal(syscall.SIGTERM)
							select {
							case <-exited:
							case <-time.After(5 * time.Second):
								_ = cmd.Process.Kill()
								<-exited
							}
						}
						break running
					case err := <-exited:
						log.Printf("智能体服务退出，稍后重试: %v", err)
						break running
					case <-deadline.C:
						if !started {
							writer.Close()
						}
					case <-ticker.C:
						if !started && agentReady(paths.Socket) {
							started = true
							ticker.Stop()
							deadline.Stop()
							report(nil)
						}
					}
				}
				ticker.Stop()
				deadline.Stop()
				writer.Close()
				if time.Since(startedAt) >= 30*time.Second {
					delay = time.Second
				}
			}
			select {
			case <-ctx.Done():
				return
			case <-time.After(delay):
			}
			if delay < 30*time.Second {
				delay *= 2
			}
		}
	}()
	stop := func() { cancel(); <-done }
	select {
	case err := <-ready:
		if err != nil {
			stop()
			return func() {}, err
		}
		return stop, nil
	case <-time.After(30 * time.Second):
		stop()
		return func() {}, fmt.Errorf("AGENT_RUNTIME_START_TIMEOUT")
	}
}
