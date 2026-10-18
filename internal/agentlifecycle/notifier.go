package agentlifecycle

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

func notifierDirectory(dataDir string) string {
	return filepath.Join(dataDir, "agents", "codex-notifiers")
}

func notifierBytes(argv []string) ([]byte, error) {
	if len(argv) == 0 || len(argv) > 64 || strings.TrimSpace(argv[0]) == "" {
		return nil, fmt.Errorf("INVALID_CODEX_NOTIFIER")
	}
	for _, arg := range argv {
		if len(arg) > 8192 || strings.ContainsRune(arg, 0) {
			return nil, fmt.Errorf("INVALID_CODEX_NOTIFIER")
		}
	}
	data, _ := json.Marshal(argv)
	if len(data) > 64_000 {
		return nil, fmt.Errorf("INVALID_CODEX_NOTIFIER")
	}
	return data, nil
}

func storeNotifier(dataDir string, argv []string) (string, error) {
	data, err := notifierBytes(argv)
	if err != nil {
		return "", err
	}
	directory := notifierDirectory(dataDir)
	if err = os.MkdirAll(directory, 0700); err != nil {
		return "", fmt.Errorf("CODEX_NOTIFIER_STORAGE_UNAVAILABLE")
	}
	digest := sha256.Sum256(data)
	path := filepath.Join(directory, hex.EncodeToString(digest[:])+".json")
	if info, err := os.Lstat(path); err == nil {
		if !info.Mode().IsRegular() || info.Mode().Perm() != 0600 || info.Size() > 64_000 {
			return "", fmt.Errorf("CODEX_NOTIFIER_STORAGE_CONFLICT")
		}
		stored, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(stored, data) {
			return "", fmt.Errorf("CODEX_NOTIFIER_STORAGE_CONFLICT")
		}
		return path, nil
	}
	temporary, err := os.CreateTemp(directory, ".notifier-")
	if err != nil {
		return "", fmt.Errorf("CODEX_NOTIFIER_STORAGE_UNAVAILABLE")
	}
	defer os.Remove(temporary.Name())
	if _, err = temporary.Write(data); err == nil {
		err = temporary.Sync()
	}
	closed := temporary.Close()
	if err == nil {
		err = closed
	}
	if err != nil || os.Rename(temporary.Name(), path) != nil {
		return "", fmt.Errorf("CODEX_NOTIFIER_STORAGE_UNAVAILABLE")
	}
	root, err := os.Open(directory)
	if err != nil {
		return "", fmt.Errorf("CODEX_NOTIFIER_STORAGE_UNAVAILABLE")
	}
	defer root.Close()
	if root.Sync() != nil {
		return "", fmt.Errorf("CODEX_NOTIFIER_STORAGE_UNAVAILABLE")
	}
	return path, nil
}

// ForwardNotification retains the original argv and appends the vendor JSON argument.
func ForwardNotification(ctx context.Context, dataDir, path, notification string, stdout, stderr io.Writer) error {
	if !filepath.IsAbs(path) || filepath.Dir(path) != notifierDirectory(dataDir) {
		return fmt.Errorf("INVALID_CODEX_NOTIFIER_PATH")
	}
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm() != 0600 || info.Size() > 64_000 {
		return fmt.Errorf("INVALID_CODEX_NOTIFIER")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("INVALID_CODEX_NOTIFIER")
	}
	digest := sha256.Sum256(data)
	if filepath.Base(path) != hex.EncodeToString(digest[:])+".json" {
		return fmt.Errorf("CODEX_NOTIFIER_CHANGED")
	}
	var argv []string
	if json.Unmarshal(data, &argv) != nil {
		return fmt.Errorf("INVALID_CODEX_NOTIFIER")
	}
	if _, err = notifierBytes(argv); err != nil {
		return err
	}
	runContext, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	command := exec.CommandContext(runContext, argv[0], append(argv[1:], notification)...)
	command.Stdout, command.Stderr = stdout, stderr
	command.WaitDelay = time.Second
	if command.Run() != nil {
		return fmt.Errorf("CODEX_NOTIFIER_FAILED")
	}
	return nil
}
