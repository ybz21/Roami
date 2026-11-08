package runtime

import (
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/ybz21/Roami/internal/sessionlifecycle"
	metadb "github.com/ybz21/Roami/internal/storage"
)

func (r Runtime) mutationLease(args []string) (func(), error) {
	if len(args) == 0 {
		return func() {}, nil
	}
	switch args[0] {
	case "send-keys", "paste-buffer", "new-window", "split-window", "respawn-pane", "respawn-window":
		for i := 1; i+1 < len(args); i++ {
			if args[i] == "-t" {
				return r.InputLease(args[i+1])
			}
		}
	}
	return func() {}, nil
}

func (r Runtime) LifecycleStore() (*sessionlifecycle.Store, error) {
	db, err := metadb.Open(r.HomeDir, metadb.Options{HomeDir: r.HomeDir, DataDir: r.DataDir})
	if err != nil {
		return nil, err
	}
	return sessionlifecycle.New(db, db.Path()), nil
}

func (r Runtime) CheckLifecycle(resource, directory string) error {
	if r.HomeDir == "" {
		return nil
	}
	store, err := r.LifecycleStore()
	if err != nil {
		return err
	}
	ctx := r.Context
	if ctx == nil {
		ctx = context.Background()
	}
	return store.Check(ctx, resource, directory)
}

func (r Runtime) InputLease(target string) (func(), error) {
	if r.HomeDir == "" {
		return func() {}, nil
	}
	resource := strings.TrimPrefix(target, "=")
	resource, _, _ = strings.Cut(resource, ":")
	if err := r.CheckLifecycle(resource, ""); err != nil {
		return nil, err
	}
	store, err := r.LifecycleStore()
	if err != nil {
		return nil, err
	}
	ctx := r.Context
	if ctx == nil {
		ctx = context.Background()
	}
	unlock, err := store.Acquire(ctx, "resource:"+resource, true)
	if err != nil {
		return nil, err
	}
	if err = r.CheckLifecycle(resource, ""); err != nil {
		unlock()
		return nil, err
	}
	return unlock, nil
}

func (r Runtime) WorkspaceLease(directory string) (func(), error) {
	if r.HomeDir == "" || directory == "" {
		return func() {}, nil
	}
	if err := r.CheckLifecycle("", directory); err != nil {
		return nil, err
	}
	store, err := r.LifecycleStore()
	if err != nil {
		return nil, err
	}
	ctx := r.Context
	if ctx == nil {
		ctx = context.Background()
	}
	unlock, err := store.Acquire(ctx, "workspace:"+sessionlifecycle.CanonicalPath(directory), true)
	if err != nil {
		return nil, err
	}
	if err = r.CheckLifecycle("", directory); err != nil {
		unlock()
		return nil, err
	}
	return unlock, nil
}

// The server process identity prevents an old cleanup from targeting a recreated session.
func (r Runtime) SessionIdentity(name string) (string, error) {
	rows, err := r.ObserveSessionRows()
	if err != nil {
		return "", err
	}
	for _, row := range rows {
		if row.Name != name {
			continue
		}
		server, err := r.TmuxOutput("list-sessions", "-F", "#{pid}:#{start_time}")
		if err != nil {
			return "", err
		}
		serverID := strings.Split(strings.TrimSpace(server), "\n")[0]
		pid, _, _ := strings.Cut(serverID, ":")
		if stat, e := os.ReadFile("/proc/" + pid + "/stat"); e == nil {
			end := strings.LastIndexByte(string(stat), ')')
			if end >= 0 {
				fields := strings.Fields(string(stat[end+1:]))
				if len(fields) > 19 {
					serverID += ":" + fields[19]
				}
			}
		}
		return fmt.Sprintf("%s:%s:%d", serverID, row.TmuxID, row.Created), nil
	}
	return "", nil
}
