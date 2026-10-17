package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	metadb "github.com/ybz21/Roami/internal/storage"
)

func globalPaths(args []string) ([]string, error) {
	keys := map[string]string{"--home": "ROAMI_HOME", "--data-dir": "ROAMI_DATA", "--database-dir": "ROAMI_DATABASE_DIR", "--backup-dir": "ROAMI_BACKUP_DIR", "--config": "ROAMI_CONFIG"}
	for len(args) > 0 {
		key, value, hasValue := strings.Cut(args[0], "=")
		env, ok := keys[key]
		if !ok {
			break
		}
		args = args[1:]
		if !hasValue {
			if len(args) == 0 {
				return nil, fmt.Errorf("%s requires a path", key)
			}
			value = args[0]
			args = args[1:]
		}
		if value == "" {
			return nil, fmt.Errorf("%s requires a nonempty path", key)
		}
		if strings.HasPrefix(value, "~/") {
			home, _ := os.UserHomeDir()
			value = filepath.Join(home, value[2:])
		}
		abs, e := filepath.Abs(value)
		if e != nil {
			return nil, e
		}
		if e = os.Setenv(env, abs); e != nil {
			return nil, e
		}
	}
	return args, nil
}

func instanceLease() (func(), error) {
	p, e := metadb.ResolvePaths("", "")
	if e != nil {
		return nil, e
	}
	for key, value := range map[string]string{"ROAMI_HOME": p.Home, "ROAMI_DATA": p.Data, "ROAMI_DATABASE_DIR": p.Database, "ROAMI_BACKUP_DIR": p.Backup} {
		if e = os.Setenv(key, value); e != nil {
			return nil, e
		}
	}
	if _, e = metadb.Open(p.Home, metadb.Options{HomeDir: p.Home, DataDir: p.Data}); e != nil {
		return nil, e
	}
	return p.Lock("storage", false)
}
