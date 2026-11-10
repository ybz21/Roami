package modelgateway

import (
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/ybz21/Roami/internal/modelplugins"
	metadb "github.com/ybz21/Roami/internal/storage"
	"golang.org/x/sys/unix"
)

func Socket(agentSocket string) string {
	return filepath.Join(filepath.Dir(agentSocket), "model-"+strings.TrimPrefix(filepath.Base(agentSocket), "agent-"))
}

// The lock survives socket unlinking and prevents two supervisors recovering each other's calls.
func Start(paths metadb.Paths, socket string) (func(), error) {
	if err := os.MkdirAll(filepath.Dir(socket), 0700); err != nil {
		return nil, err
	}
	fd, err := unix.Open(socket+".lock", unix.O_CREAT|unix.O_RDWR|unix.O_NOFOLLOW, 0600)
	if err != nil {
		return nil, err
	}
	locked := false
	defer func() {
		if !locked {
			unix.Close(fd)
		}
	}()
	if err = unix.Flock(fd, unix.LOCK_EX|unix.LOCK_NB); err != nil {
		return nil, fmt.Errorf("MODEL_GATEWAY_ALREADY_RUNNING: %w", err)
	}
	if info, err := os.Lstat(socket); err == nil {
		if info.Mode()&os.ModeSocket == 0 {
			return nil, fmt.Errorf("MODEL_GATEWAY_SOCKET_UNSAFE")
		}
		if err = os.Remove(socket); err != nil {
			return nil, err
		}
	} else if !os.IsNotExist(err) {
		return nil, err
	}
	listener, err := net.Listen("unix", socket)
	if err != nil {
		return nil, err
	}
	if err = os.Chmod(socket, 0600); err != nil {
		listener.Close()
		return nil, err
	}
	ledger, err := Open(paths)
	if err == nil {
		err = ledger.Recover()
	}
	if err == nil {
		if compactErr := ledger.Compact(); compactErr != nil {
			log.Printf("model gateway daily retention: %v", compactErr)
		}
	}
	if err != nil {
		listener.Close()
		return nil, err
	}
	handler := NewHandler(ledger)
	catalog, err := openCatalog(ledger)
	if err != nil {
		listener.Close()
		return nil, err
	}
	public, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", catalog.value.Port))
	if err != nil {
		listener.Close()
		return nil, err
	}
	catalog.value.Port = public.Addr().(*net.TCPAddr).Port
	catalog.baseURL = "http://" + public.Addr().String()
	catalog.agentSocket = filepath.Join(filepath.Dir(socket), "agent-"+strings.TrimPrefix(filepath.Base(socket), "model-"))
	if err = catalog.persist(catalog.value); err != nil {
		public.Close()
		listener.Close()
		return nil, err
	}
	plugins, err := modelplugins.NewManager(filepath.Join(paths.Data, "model-plugins"))
	if err != nil {
		public.Close()
		listener.Close()
		return nil, err
	}
	plugins.AuthChanged = handler.pluginAuthChanged
	handler.Plugins = plugins
	catalog.plugins = plugins
	handler.Catalog = catalog
	publicServer := &http.Server{Handler: http.HandlerFunc(handler.publicModels), ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second}
	publicDone := make(chan struct{})
	go func() { defer close(publicDone); _ = publicServer.Serve(public) }()
	server := &http.Server{Handler: handler, ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second}
	done := make(chan struct{})
	go func() { defer close(done); _ = server.Serve(listener) }()
	maintenanceStop, maintenanceDone := make(chan struct{}), make(chan struct{})
	go func() {
		defer close(maintenanceDone)
		ticker := time.NewTicker(time.Hour)
		defer ticker.Stop()
		for {
			select {
			case <-maintenanceStop:
				return
			case <-ticker.C:
				if err := ledger.Compact(); err != nil {
					log.Printf("model gateway daily retention: %v", err)
				}
			}
		}
	}()
	locked = true
	var once sync.Once
	return func() {
		once.Do(func() {
			close(maintenanceStop)
			<-maintenanceDone
			handler.mu.Lock()
			handler.closing = true
			handler.mu.Unlock()
			_ = server.Close()
			_ = publicServer.Close()
			<-publicDone
			<-done
			// Close cancels requests; wait for their deferred ledger writes before unlocking.
			handler.wait.Wait()
			plugins.Close()
			handler.Client.Transport.(*http.Transport).CloseIdleConnections()
			_ = unix.Flock(fd, unix.LOCK_UN)
			_ = unix.Close(fd)
		})
	}, nil
}
