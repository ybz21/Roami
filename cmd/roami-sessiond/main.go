// Command roami-sessiond is the minimal standalone Go session host that owns native PTYs,
// server-side VT state, window/split layouts, and reconnectable pane streams independently of the Web server.
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/ybz21/Roami/internal/sessionhost"
	"github.com/ybz21/Roami/internal/sessionipc"
	"github.com/ybz21/Roami/internal/terminal"
)

var version = "dev"

func main() {
	instanceRoot := flag.String("instance-root", "", "Roami instance data directory (default ~/.roami)")
	hostID := flag.String("host-id", "", "Unique host instance ID (auto-generated if omitted)")
	logsDir := flag.String("logs-dir", "", "Terminal output logs directory (default <instance-root>/logs)")
	activate := flag.Bool("activate", true, "Switch current_host pointer if no host is active yet")
	flag.Parse()

	root := *instanceRoot
	if root == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			log.Fatalf("roami-sessiond: resolve home dir: %v", err)
		}
		root = filepath.Join(home, ".roami")
	}
	if abs, err := filepath.Abs(root); err == nil {
		root = abs
	}
	logs := *logsDir
	if logs == "" {
		logs = filepath.Join(root, "logs")
	}
	id := *hostID
	if id == "" {
		id = fmt.Sprintf("host-%d-%d", os.Getpid(), time.Now().UnixMilli())
	}

	coordPath := filepath.Join(root, "session-host.db")
	coord, err := sessionhost.OpenCoordDB(coordPath)
	if err != nil {
		log.Fatalf("roami-sessiond: open coord db: %v", err)
	}
	defer coord.Close()

	backend := terminal.NewBackend()
	procID := ""
	if insp, ok := backend.(terminal.ProcessInspector); ok {
		procID, _ = insp.ProcessIdentity(os.Getpid())
	}

	host := sessionhost.NewHost(sessionhost.Config{
		HostID:  id,
		LogsDir: logs,
		Coord:   coord,
		Backend: backend,
	})
	srv, err := sessionipc.NewServer(host, root)
	if err != nil {
		log.Fatalf("roami-sessiond: listen ipc: %v", err)
	}
	defer srv.Close()

	desc := srv.Descriptor()
	descPath := filepath.Join(root, "hosts", id+".json")
	if err := sessionipc.WriteEndpointDescriptor(descPath, desc); err != nil {
		log.Fatalf("roami-sessiond: write endpoint descriptor: %v", err)
	}
	defer os.Remove(descPath)

	if err := coord.RegisterHost(sessionhost.HostRecord{
		HostID:      id,
		Version:     version,
		ProtocolMin: desc.ProtocolMin,
		ProtocolMax: desc.ProtocolMax,
		Endpoint:    desc.Address,
		TokenPath:   descPath,
		PID:         os.Getpid(),
		ProcessID:   procID,
		State:       sessionhost.HostStateReady,
	}); err != nil {
		log.Fatalf("roami-sessiond: register host: %v", err)
	}

	if *activate {
		if ptr, err := coord.Pointer(); err == nil && ptr.CurrentHost == "" {
			_, _ = coord.SwitchHost(id, "", ptr.Generation, sessionhost.DefaultMaxDrainingHosts)
		}
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigCh := make(chan os.Signal, 2)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sigCh
		host.SetDraining(true)
		log.Printf("roami-sessiond (%s): draining (%d active panes)", id, host.ActivePaneCount())
		ticker := time.NewTicker(200 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-sigCh:
				// Second signal forces immediate shutdown.
				host.Shutdown(context.Background())
				cancel()
				return
			case <-ticker.C:
				if host.ActivePaneCount() == 0 {
					pending, _ := coord.PendingOperations(id)
					if pending == 0 {
						_ = coord.MarkRetiring(id)
						cancel()
						return
					}
				}
			}
		}
	}()

	log.Printf("roami-sessiond (%s) listening on %s://%s", id, desc.Network, desc.Address)
	if err := srv.Serve(ctx); err != nil {
		log.Fatalf("roami-sessiond: serve: %v", err)
	}
	_ = coord.MarkRetired(id)
}
