package automation

import (
	"crypto/sha256"
	_ "embed"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	metadb "github.com/ybz21/Roami/internal/storage"
)

//go:embed launcher.sh
var launcher string

//go:embed driver.mjs
var driver string

//go:embed operation-receipts.mjs
var operationReceipts string

//go:embed browser-observation.mjs
var browserObservation string

// Run keeps Playwright and its daemon behind the same public executable.
func Run(args []string) error {
	content := strings.ReplaceAll(launcher, "@@DRIVER@@", driver)
	content = strings.ReplaceAll(content, "@@OPERATION_RECEIPTS@@", operationReceipts)
	content = strings.ReplaceAll(content, "@@BROWSER_OBSERVATION@@", browserObservation)
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" || args[0] == "--version" {
		cmd := exec.Command("bash", append([]string{"-s", "--"}, args...)...)
		cmd.Stdin = strings.NewReader(content)
		cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
		return cmd.Run()
	}
	paths, err := metadb.ResolvePaths("", "")
	if err != nil {
		return err
	}

	hash := fmt.Sprintf("%x", sha256.Sum256([]byte(content)))
	dir := filepath.Join(paths.Data, "cache", "chrome", hash[:16])
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	path := filepath.Join(dir, "launcher")
	if _, err := os.Stat(path); os.IsNotExist(err) {
		f, e := os.CreateTemp(dir, "launcher-*")
		if e != nil {
			return e
		}
		defer os.Remove(f.Name())
		if _, e = f.WriteString(content); e != nil {
			f.Close()
			return e
		}
		if e = f.Chmod(0700); e != nil {
			f.Close()
			return e
		}
		if e = f.Close(); e != nil {
			return e
		}
		if e = os.Rename(f.Name(), path); e != nil {
			return e
		}
	}
	cmd := exec.Command("bash", append([]string{path}, args...)...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	cmd.Env = append(os.Environ(), "ROAMI_HOME="+paths.Home, "ROAMI_DATA="+paths.Data)
	return cmd.Run()
}
