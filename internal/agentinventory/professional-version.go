package agentinventory

import (
	"context"
	"os"
	"sync"
	"time"
)

type professionalVersion struct {
	path    string
	info    os.FileInfo
	done    chan struct{}
	version string
	until   time.Time
}

var professionalVersions = struct {
	sync.Mutex
	entries map[string]*professionalVersion
}{entries: make(map[string]*professionalVersion)}

func readProfessionalVersion(ctx context.Context, row *ProfessionalAgent, force bool) {
	if !row.Installed {
		return
	}
	row.VersionState = "unavailable"
	info, err := os.Stat(row.Binary)
	if err != nil || ctx.Err() != nil {
		return
	}
	professionalVersions.Lock()
	entry := professionalVersions.entries[row.Kind]
	matching := entry != nil && entry.path == row.Binary && os.SameFile(entry.info, info) &&
		entry.info.Size() == info.Size() && entry.info.ModTime().Equal(info.ModTime())
	if matching {
		select {
		case <-entry.done:
			matching = !force && time.Now().Before(entry.until)
		default:
		}
	}
	if !matching {
		entry = &professionalVersion{path: row.Binary, info: info, done: make(chan struct{})}
		professionalVersions.entries[row.Kind] = entry
		go func() {
			// A disconnected reader must not cancel a probe shared by other clients.
			version := probeProfessionalVersion(context.Background(), entry.path)
			ttl := 5 * time.Minute
			if version == "" {
				ttl = time.Minute
			}
			professionalVersions.Lock()
			entry.version, entry.until = version, time.Now().Add(ttl)
			close(entry.done)
			professionalVersions.Unlock()
		}()
	}
	professionalVersions.Unlock()
	select {
	case <-ctx.Done():
		return
	case <-entry.done:
		row.Version = entry.version
		if row.Version != "" {
			row.VersionState = "available"
		}
	}
}
