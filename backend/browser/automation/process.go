package automation

import (
	"crypto/sha256"
	_ "embed"
	"encoding/json"
	"fmt"
	"github.com/ybz21/Roami/internal/browsertabs"
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

//go:embed scoped-cdp.mjs
var scopedCDP string

// Run keeps Playwright and its daemon behind the same public executable.
func Run(args []string) error {
	content := strings.ReplaceAll(launcher, "@@DRIVER@@", driver)
	content = strings.ReplaceAll(content, "@@OPERATION_RECEIPTS@@", operationReceipts)
	content = strings.ReplaceAll(content, "@@BROWSER_OBSERVATION@@", browserObservation)
	content = strings.ReplaceAll(content, "@@SCOPED_CDP@@", scopedCDP)
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

	if len(args) > 0 && args[0] == "_tab-event" {
		if len(args) < 2 {
			return browsertabs.ErrInvalid
		}
		var e browsertabs.Event
		if err := json.Unmarshal([]byte(args[1]), &e); err != nil {
			return err
		}
		result, err := browsertabs.Apply(paths.Data, e)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(result)
	}

	if len(args) > 0 && args[0] == "new" {
		release, err := browsertabs.CreationLock(paths.Data)
		if err != nil {
			return err
		}
		defer release()
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
	if binary, err := os.Executable(); err == nil {
		cmd.Env = append(cmd.Env, "ROAMI_CHROME_CATALOG_BIN="+binary)
	}
	return cmd.Run()
}
