package plugin

import (
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	metadb "github.com/ybz21/Roami/internal/storage"
)

func (e Env) HostSession(base string) string {
	sum := sha256.Sum256([]byte(e.RT.HomeDir + "\x00" + e.RT.DataDir))
	return fmt.Sprintf("%s-%x", base, sum[:8])
}

// tmux's server environment can belong to a different Roami instance.
func (e Env) hostCommand(self string, args ...string) (string, error) {
	p, err := metadb.ResolvePaths(e.RT.HomeDir, e.RT.DataDir)
	if err != nil {
		return "", err
	}
	cfg := filepath.Join(p.Home, "config.yaml")
	if os.Getenv("ROAMI_HOME") == p.Home && os.Getenv("ROAMI_CONFIG") != "" {
		cfg = os.Getenv("ROAMI_CONFIG")
	}
	words := []string{"env", "ROAMI_HOME=" + p.Home, "ROAMI_DATA=" + p.Data, "ROAMI_DATABASE_DIR=" + p.Database, "ROAMI_BACKUP_DIR=" + p.Backup, "ROAMI_CONFIG=" + cfg}
	if e.RT.TmuxBin != "" {
		words = append(words, "TMUX_BIN="+e.RT.TmuxBin)
	}
	words = append(words, self)
	words = append(words, args...)
	for i, word := range words {
		words[i] = "'" + strings.ReplaceAll(word, "'", "'\"'\"'") + "'"
	}
	return strings.Join(words, " "), nil
}

func (e Env) startHostSession(base string, args ...string) error {
	self, err := os.Executable()
	if err != nil {
		return err
	}
	command, err := e.hostCommand(self, args...)
	if err != nil {
		return err
	}
	return e.RT.Tmux("new-session", "-d", "-s", e.HostSession(base), command)
}
