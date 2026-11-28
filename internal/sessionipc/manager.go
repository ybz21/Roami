package sessionipc

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessioncoord"
)

// Manager connects to the active and draining roami-term hosts for an instance root,
// optionally spawning a detached host on demand when none is running.
type Manager struct {
	instanceRoot string
	termBin      string

	mu      sync.Mutex
	clients map[string]*Client
}

func NewManager(instanceRoot, termBin string) *Manager {
	return &Manager{
		instanceRoot: instanceRoot,
		termBin:      termBin,
		clients:      make(map[string]*Client),
	}
}

// ConnectExisting connects to an already-running active host without creating
// session-host.db or spawning a new roami-term process.
func (m *Manager) ConnectExisting(ctx context.Context) (*Client, sessioncoord.HostPointer, error) {
	dbPath := filepath.Join(m.instanceRoot, "session-host.db")
	if _, err := os.Stat(dbPath); err != nil {
		return nil, sessioncoord.HostPointer{}, err
	}
	coord, err := sessioncoord.Open(dbPath)
	if err != nil {
		return nil, sessioncoord.HostPointer{}, err
	}
	defer coord.Close()

	ptr, err := coord.Pointer()
	if err != nil {
		return nil, sessioncoord.HostPointer{}, err
	}
	if ptr.CurrentHost == "" {
		return nil, ptr, fmt.Errorf("sessionipc: no active host recorded")
	}
	cli, err := m.dialHost(ctx, coord, ptr.CurrentHost)
	return cli, ptr, err
}

// ConnectActive returns a live IPC client to the current active host, spawning one on demand
// when termBin is configured and no active host is reachable.
func (m *Manager) ConnectActive(ctx context.Context) (*Client, sessioncoord.HostPointer, error) {
	coord, err := sessioncoord.Open(filepath.Join(m.instanceRoot, "session-host.db"))
	if err != nil {
		return nil, sessioncoord.HostPointer{}, err
	}
	defer coord.Close()

	ptr, err := coord.Pointer()
	if err != nil {
		return nil, sessioncoord.HostPointer{}, err
	}
	if ptr.CurrentHost != "" {
		if cli, err := m.dialHost(ctx, coord, ptr.CurrentHost); err == nil {
			return cli, ptr, nil
		}
	}
	if m.termBin == "" {
		return nil, ptr, fmt.Errorf("sessionipc: no active roami-term for %s", m.instanceRoot)
	}

	hostID := fmt.Sprintf("host-%d-%d", os.Getpid(), time.Now().UnixMilli())
	if _, err := SpawnDetached(m.termBin, "--instance-root", m.instanceRoot, "--host-id", hostID, "--activate=false"); err != nil {
		return nil, ptr, err
	}
	descPath := filepath.Join(m.instanceRoot, "hosts", hostID+".json")
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if _, err := ReadEndpointDescriptor(descPath); err == nil {
			break
		}
		select {
		case <-ctx.Done():
			return nil, ptr, ctx.Err()
		case <-time.After(30 * time.Millisecond):
		}
	}
	ptr, err = coord.Pointer()
	if err != nil {
		return nil, ptr, err
	}
	nextPtr, err := coord.SwitchHost(hostID, ptr.CurrentHost, ptr.Generation, sessioncoord.DefaultMaxDrainingHosts)
	if err != nil {
		// Another caller may have raced and switched first; re-read pointer and connect.
		nextPtr, err = coord.Pointer()
		if err != nil || nextPtr.CurrentHost == "" {
			return nil, nextPtr, fmt.Errorf("sessionipc: failed to activate spawned host: %w", err)
		}
	}
	cli, err := m.dialHost(ctx, coord, nextPtr.CurrentHost)
	return cli, nextPtr, err
}

// Router builds a multi-host SessionBackend router containing the active host and any live draining hosts.
func (m *Manager) Router(ctx context.Context, fallbackTmux sessionbackend.SessionBackend) (*sessionbackend.Router, error) {
	active, ptr, err := m.ConnectActive(ctx)
	if err != nil {
		return nil, err
	}
	backends := map[string]sessionbackend.SessionBackend{
		ptr.CurrentHost: active,
	}
	if fallbackTmux != nil {
		backends["tmux"] = fallbackTmux
	}
	if coord, err := sessioncoord.Open(filepath.Join(m.instanceRoot, "session-host.db")); err == nil {
		defer coord.Close()
		if hosts, err := coord.ListHosts(); err == nil {
			for _, h := range hosts {
				if h.HostID == ptr.CurrentHost || h.State != sessioncoord.HostStateDraining {
					continue
				}
				if cli, err := m.dialHost(ctx, coord, h.HostID); err == nil {
					backends[h.HostID] = cli
				}
			}
		}
	}
	return sessionbackend.NewRouter(ptr.CurrentHost, backends), nil
}

func (m *Manager) dialHost(ctx context.Context, coord *sessioncoord.DB, hostID string) (*Client, error) {
	m.mu.Lock()
	if existing, ok := m.clients[hostID]; ok {
		m.mu.Unlock()
		if _, err := existing.Health(ctx); err == nil {
			return existing, nil
		}
		_ = existing.CloseConn()
		m.mu.Lock()
		delete(m.clients, hostID)
	}
	m.mu.Unlock()

	rec, err := coord.Host(hostID)
	if err != nil {
		return nil, err
	}
	descPath := rec.TokenPath
	if descPath == "" {
		descPath = filepath.Join(m.instanceRoot, "hosts", hostID+".json")
	}
	desc, err := ReadEndpointDescriptor(descPath)
	if err != nil {
		return nil, err
	}
	cli, err := Dial(ctx, desc)
	if err != nil {
		return nil, err
	}
	m.mu.Lock()
	m.clients[hostID] = cli
	m.mu.Unlock()
	return cli, nil
}

func (m *Manager) Close() {
	m.mu.Lock()
	defer m.mu.Unlock()
	for id, cli := range m.clients {
		_ = cli.CloseConn()
		delete(m.clients, id)
	}
}
