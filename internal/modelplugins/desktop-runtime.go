package modelplugins

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
)

// Native desktop access is limited to the audited upstream Doubao Work 0.1.5
// code. Other uploaded packages still require the OS sandbox.
const doubaoDesktopDigest = "d82b79ada7a25bb422cde30a9102c5eac08e3cbf166e53c6de646209d662bdc5"

var doubaoRuntimeFiles = []string{"package.json", "index.mjs", "cdp.mjs", "doubao.mjs", "openai.mjs", "prompt.mjs", "opencode.mjs", "opencode2.mjs"}

func trustedDoubaoDirectory(dir string) bool {
	allowed := map[string]bool{"README.md": true, "LICENSE": true, "LICENSE.md": true, ".roami-package.json": true, "doubao-work.test.mjs": true}
	for _, name := range doubaoRuntimeFiles {
		allowed[name] = true
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return false
	}
	for _, entry := range entries {
		if !allowed[entry.Name()] || !entry.Type().IsRegular() {
			return false
		}
	}
	if data, err := os.ReadFile(filepath.Join(dir, "doubao-work.test.mjs")); err == nil {
		sum := sha256.Sum256(bytes.ReplaceAll(data, []byte("\r\n"), []byte("\n")))
		if hex.EncodeToString(sum[:]) != "090666e10bbd7a5534128b449bbedc850e2da279f0571576907ecac89c2a23f1" {
			return false
		}
	}
	names := append([]string(nil), doubaoRuntimeFiles...)
	sort.Strings(names)
	hash := sha256.New()
	for _, name := range names {
		data, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			return false
		}
		data = bytes.ReplaceAll(data, []byte("\r\n"), []byte("\n"))
		if name == "package.json" {
			var parsed any
			if json.Unmarshal(data, &parsed) != nil {
				return false
			}
			data, err = json.Marshal(parsed)
			if err != nil {
				return false
			}
		}
		fmt.Fprintf(hash, "%d:%s:%d:", len(name), name, len(data))
		_, _ = hash.Write(data)
	}
	return hex.EncodeToString(hash.Sum(nil)) == doubaoDesktopDigest
}
func desktopAppPath(platform, home, localData string) string {
	if override := os.Getenv("DOUBAO_WORK_APP"); override != "" {
		if info, err := os.Stat(override); err == nil && info.Mode().IsRegular() {
			return override
		}
	}
	paths := []string{}
	switch platform {
	case "darwin":
		for _, app := range []string{"DoubaoWork", "Doubao"} {
			paths = append(paths, filepath.Join("/Applications", app+".app", "Contents", "MacOS", app), filepath.Join(home, "Applications", app+".app", "Contents", "MacOS", app))
		}
	case "windows":
		if localData == "" {
			localData = filepath.Join(home, "AppData", "Local")
		}
		for _, app := range []string{"DoubaoWork", "Doubao"} {
			paths = append(paths, filepath.Join(localData, app, "Application", "app", app+".exe"))
		}
	}
	for _, candidate := range paths {
		if info, err := os.Stat(candidate); err == nil && info.Mode().IsRegular() {
			return candidate
		}
	}
	return ""
}
func DesktopAppMissing(provider string) bool {
	if provider != "doubao-work" || DesktopUnavailable(provider) {
		return false
	}
	home, _ := os.UserHomeDir()
	return desktopAppPath(runtime.GOOS, home, os.Getenv("LOCALAPPDATA")) == ""
}
func desktopCommand(p SandboxPaths, platform, home, localData string) (*exec.Cmd, error) {
	if platform != "darwin" && platform != "windows" {
		return nil, errors.New("MODEL_PLUGIN_DESKTOP_UNAVAILABLE")
	}
	if !trustedDoubaoDirectory(p.Package) {
		return nil, errors.New("MODEL_PLUGIN_DESKTOP_PACKAGE_UNTRUSTED")
	}
	temp := filepath.Join(p.State, "tmp")
	if err := os.MkdirAll(temp, 0700); err != nil {
		return nil, err
	}
	command := exec.Command(p.Bun, "--no-install", "--smol", filepath.Join(p.Runtime, "magpie-host.js"))
	command.Dir = p.State
	command.Env = []string{"HOME=" + p.State, "USERPROFILE=" + p.State, "DOUBAO_WORK_HOME=" + filepath.Join(p.State, "doubao-work"), "TMPDIR=" + temp, "TEMP=" + temp, "TMP=" + temp, "PATH=" + os.Getenv("PATH")}
	for _, key := range []string{"SystemRoot", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "TZ"} {
		if value := os.Getenv(key); value != "" {
			command.Env = append(command.Env, key+"="+value)
		}
	}
	if app := desktopAppPath(platform, home, localData); app != "" {
		command.Env = append(command.Env, "DOUBAO_WORK_APP="+app)
	}
	return command, nil
}
