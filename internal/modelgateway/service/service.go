package service

import (
	"fmt"
	"log"
	"net"
	"net/http"
	"path/filepath"
	"sync"
	"time"

	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
	"github.com/ybz21/Roami/internal/modelgateway/monitor"
	"github.com/ybz21/Roami/internal/modelplugins"
	metadb "github.com/ybz21/Roami/internal/storage"
	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func Start(paths metadb.Paths, socket string) (func(), error) {
	listener, unlock, err := httpapi.ListenManagement(socket)
	if err != nil {
		return nil, err
	}
	serving := false
	defer func() {
		if !serving {
			unlock()
		}
	}()
	ledger, err := openState(paths)
	if err == nil {
		err = ledger.accounting.Recover()
	}
	if err == nil {
		if compactErr := ledger.accounting.Compact(); compactErr != nil {
			log.Printf("model gateway daily retention: %v", compactErr)
		}
	}
	if err != nil {
		listener.Close()
		return nil, err
	}
	handler := NewHandler(ledger)
	store, err := monitor.Open(filepath.Join(paths.Database, "models", "monitor.ring"), monitor.DefaultCapacity, time.Now)
	if err != nil {
		listener.Close()
		return nil, err
	}
	handler.Monitor = store
	monitorOwned := false
	defer func() {
		if !monitorOwned {
			_ = store.Close()
		}
	}()
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
	catalog.agentSocket = httpapi.AgentSocket(socket)
	if err = catalog.persist(catalog.value); err != nil {
		public.Close()
		listener.Close()
		return nil, err
	}
	rt := runtime.Runtime{EnvFile: filepath.Join(paths.Data, "env")}
	plugins, err := modelplugins.NewManager(filepath.Join(paths.Data, "model-plugins"), rt.EnvPairs)
	if err != nil {
		public.Close()
		listener.Close()
		return nil, err
	}
	plugins.AuthChanged = handler.pluginAuthChanged
	handler.Plugins = plugins
	catalog.plugins = plugins
	handler.Catalog = catalog
	if err := handler.network.restore(catalog, http.HandlerFunc(handler.serveGatewayLAN)); err != nil {
		log.Printf("model gateway LAN listener: %v", err)
	}
	publicServer := &http.Server{Handler: http.HandlerFunc(handler.publicModels), ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second}
	publicDone := make(chan struct{})
	go func() { defer close(publicDone); _ = publicServer.Serve(public) }()
	server := &http.Server{Handler: handler, ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second}
	done := make(chan struct{})
	go func() { defer close(done); _ = server.Serve(listener) }()
	maintenanceStop, maintenanceDone := make(chan struct{}), make(chan struct{})
	go func() {
		defer close(maintenanceDone)
		ticker := time.NewTicker(time.Minute)
		lastCompact := time.Now()
		defer ticker.Stop()
		for {
			select {
			case <-maintenanceStop:
				return
			case <-ticker.C:
				if err := store.Maintain(); err != nil {
					log.Printf("model gateway monitor maintenance failed")
				}
				if time.Since(lastCompact) >= time.Hour {
					if err := ledger.accounting.Compact(); err != nil {
						log.Printf("model gateway daily retention: %v", err)
					}
					lastCompact = time.Now()
				}
			}
		}
	}()
	serving = true
	monitorOwned = true
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
			handler.network.close(catalog)
			<-publicDone
			<-done
			// Close cancels requests; wait for their deferred ledger writes before unlocking.
			handler.wait.Wait()
			_ = store.Close()
			plugins.Close()
			handler.Client.CloseIdleConnections()
			handler.uncheckedTLS.CloseIdleConnections()
			unlock()
		})
	}, nil
}
