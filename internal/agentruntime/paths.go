// Package agentruntime adapts the Python runtime to Roami's storage and HTTP boundary.
package agentruntime

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"syscall"

	metadb "github.com/ybz21/Roami/internal/storage"
)

type Paths struct {
	Storage    metadb.Paths `json:"storage"`
	Database   string       `json:"database"`
	Socket     string       `json:"socket"`
	Config     string       `json:"config"`
	InstanceID string       `json:"instanceId"`
}

func Resolve(home, data string) (Paths, error) {
	p, err := metadb.ResolvePaths(home, data)
	if err != nil {
		return Paths{}, err
	}
	layout, err := p.ReadLayout()
	if err != nil {
		return Paths{}, err
	}
	root := filepath.Join(p.Data, "run")

	sum := sha256.Sum256([]byte(layout.Instance + ":" + p.Data))
	socket := filepath.Join(root, "agent-"+hex.EncodeToString(sum[:8])+".sock")
	if len(socket) > 103 {
		root = filepath.Join("/tmp", fmt.Sprintf("roami-agent-%d", os.Geteuid()))
		if err := os.Mkdir(root, 0700); err != nil && !os.IsExist(err) {
			return Paths{}, err
		}
		info, err := os.Lstat(root)
		if err != nil {
			return Paths{}, err
		}
		st, ok := info.Sys().(*syscall.Stat_t)
		if !info.IsDir() || info.Mode().Perm() != 0700 || !ok || int(st.Uid) != os.Geteuid() {
			return Paths{}, fmt.Errorf("AGENT_SOCKET_DIRECTORY_UNSAFE")
		}
		socket = filepath.Join(root, "agent-"+hex.EncodeToString(sum[:8])+".sock")
	}
	return Paths{Storage: p, Database: filepath.Join(p.Database, "agents", "runtime.db"), Socket: socket,
		Config: filepath.Join(p.Home, "agent.toml"), InstanceID: layout.Instance}, nil
}

func (p Paths) Descriptor(state string) metadb.DatabaseDescriptor {
	return metadb.DatabaseDescriptor{ID: "agent-runtime", Kind: "agent", Owner: "python-agent", Path: p.Database, State: state}
}
