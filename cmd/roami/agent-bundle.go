package main

import (
	"archive/tar"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	metadb "github.com/ybz21/Roami/internal/storage"
	"io"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"runtime"
	"strings"
)

type agentBundleManifest struct {
	Format  int               `json:"format"`
	Version string            `json:"version"`
	Target  string            `json:"target"`
	Python  string            `json:"python"`
	Schema  int               `json:"schema"`
	Files   map[string]string `json:"files"`
}

func runAgentBundle(args []string) int {
	fs := flag.NewFlagSet("agent install-bundle", flag.ContinueOnError)
	expectedVersion := fs.String("expected-version", "", "release tag to require")
	activate := fs.Bool("activate", false, "activate a prepared release")
	check := fs.Bool("check", false, "check the live database without migration")
	binDir := fs.String("bin-dir", "", "stable command directory")
	archive := fs.String("archive", "", "complete release archive")
	destination := fs.String("destination", "", "final version directory")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if *destination == "" || fs.NArg() != 0 || (!*activate && !*check && *archive == "") {
		fmt.Fprintln(os.Stderr, "--archive and --destination are required")
		return 2
	}
	var err error
	if *check {
		err = checkAgentBundle(*destination)
		if err == nil && *expectedVersion != "" {
			raw, problem := os.ReadFile(filepath.Join(*destination, "manifest.json"))
			var manifest agentBundleManifest
			if problem != nil {
				err = problem
			} else if json.Unmarshal(raw, &manifest) != nil || manifest.Version != *expectedVersion {
				err = fmt.Errorf("BUNDLE_RELEASE_VERSION_MISMATCH")
			}
		}
	} else if *activate {
		err = activateAgentBundle(*destination, *binDir)
	} else {
		err = installAgentBundle(*archive, *destination, *expectedVersion)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}

func installAgentBundle(archive, destination string, expectedVersion ...string) (result error) {
	if _, err := os.Lstat(destination); err == nil {
		return fmt.Errorf("BUNDLE_DESTINATION_EXISTS: %s", destination)
	} else if !os.IsNotExist(err) {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(destination), 0700); err != nil {
		return err
	}
	if err := os.Mkdir(destination, 0700); err != nil {
		return err
	}
	defer func() {
		if result != nil {
			_ = os.RemoveAll(destination)
		}
	}()
	if err := extractAgentBundle(archive, destination); err != nil {
		return err
	}
	raw, err := os.ReadFile(filepath.Join(destination, "manifest.json"))
	if err != nil {
		return err
	}
	var manifest agentBundleManifest
	if err = json.Unmarshal(raw, &manifest); err != nil {
		return err
	}
	if manifest.Format != 1 || manifest.Target != runtime.GOOS+"-"+runtime.GOARCH || manifest.Version != version || manifest.Python == "" || manifest.Schema < 1 {
		return fmt.Errorf("BUNDLE_MANIFEST_INCOMPATIBLE")
	}
	if len(expectedVersion) > 0 && expectedVersion[0] != "" && manifest.Version != expectedVersion[0] {
		return fmt.Errorf("BUNDLE_RELEASE_VERSION_MISMATCH")
	}
	if len(manifest.Files) == 0 {
		return fmt.Errorf("BUNDLE_MANIFEST_EMPTY")
	}
	for name, expected := range manifest.Files {
		if !bundlePath(name) {
			return fmt.Errorf("BUNDLE_INVALID_PATH: %s", name)
		}
		file, err := os.Open(filepath.Join(destination, filepath.FromSlash(name)))
		if err != nil {
			return err
		}
		sum := sha256.New()
		_, err = io.Copy(sum, file)
		file.Close()
		if err != nil {
			return err
		}
		if hex.EncodeToString(sum.Sum(nil)) != expected {
			return fmt.Errorf("BUNDLE_HASH_MISMATCH: %s", name)
		}
	}
	// Reject unlisted executable or library payloads before running the bundled Python.
	err = filepath.WalkDir(destination, func(name string, entry os.DirEntry, problem error) error {
		if problem != nil {
			return problem
		}
		if entry.IsDir() {
			return nil
		}
		relative, err := filepath.Rel(destination, name)
		if err != nil {
			return err
		}
		relative = filepath.ToSlash(relative)
		if relative != "manifest.json" && manifest.Files[relative] == "" {
			return fmt.Errorf("BUNDLE_UNLISTED_FILE: %s", relative)
		}
		return nil
	})
	if err != nil {
		return err
	}
	for _, required := range []string{"bin/roami", "runtime/python/bin/python3", "runtime/requirements.txt", "runtime/pyproject.toml", "install/retire-session-entries.sh"} {
		if manifest.Files[required] == "" {
			return fmt.Errorf("BUNDLE_MISSING_FILE: %s", required)
		}
	}
	if err = setupBundledAgent(filepath.Join(destination, "runtime")); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(destination, "ready"), raw, 0600)
}

func bundlePath(name string) bool {
	return name != "" && name != "." && name != ".." && !strings.HasPrefix(name, "../") && !path.IsAbs(name) && path.Clean(name) == name && !strings.Contains(name, "\\")
}

func extractAgentBundle(archive, destination string) error {
	file, err := os.Open(archive)
	if err != nil {
		return err
	}
	defer file.Close()
	compressed, err := gzip.NewReader(file)
	if err != nil {
		return err
	}
	defer compressed.Close()
	reader := tar.NewReader(compressed)
	var total int64
	for count := 0; ; count++ {
		header, err := reader.Next()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		name := strings.TrimSuffix(header.Name, "/")
		if !bundlePath(name) || strings.HasPrefix(name, "runtime/.venv") || name == "ready" {
			return fmt.Errorf("BUNDLE_INVALID_PATH: %s", name)
		}
		total += header.Size
		if count > 100000 || header.Size < 0 || total > 4<<30 {
			return fmt.Errorf("BUNDLE_TOO_LARGE")
		}
		target := filepath.Join(destination, filepath.FromSlash(name))
		if header.Typeflag == tar.TypeDir {
			if err := os.MkdirAll(target, 0755); err != nil {
				return err
			}
			continue
		}
		if header.Typeflag != tar.TypeReg {
			return fmt.Errorf("BUNDLE_UNSUPPORTED_ENTRY: %s", name)
		}
		if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
			return err
		}
		mode := os.FileMode(0644)
		if header.Mode&0111 != 0 {
			mode = 0755
		}
		output, err := os.OpenFile(target, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
		if err != nil {
			return err
		}
		_, copyErr := io.Copy(output, reader)
		closeErr := output.Close()
		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
	}
}

func setupBundledAgent(dir string) error {
	python := filepath.Join(dir, "python", "bin", "python3")
	venv := filepath.Join(dir, ".venv")
	envPython := filepath.Join(venv, "bin", "python")
	commands := [][]string{
		{python, "-I", "-m", "venv", venv},
		{envPython, "-I", "-m", "pip", "--isolated", "install", "--no-index", "--no-cache-dir", "--only-binary=:all:", "--require-hashes", "--find-links", filepath.Join(dir, "wheels"), "-r", filepath.Join(dir, "requirements.txt")},
		{envPython, "-I", "-m", "pip", "--isolated", "check"},
		{envPython, "-I", "-c", "from roami_agent.app import Runtime; from roami_agent.server.http import create_app; from roami_agent.storage.migrations import initial_schema; assert initial_schema()"},
	}
	for _, argv := range commands {
		cmd := exec.Command(argv[0], argv[1:]...)
		cmd.Env = agentEnvironment()
		cmd.Dir = dir
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		if err := cmd.Run(); err != nil {
			return fmt.Errorf("AGENT_ENVIRONMENT_SETUP_FAILED: %w", err)
		}
	}
	return nil
}

func checkAgentBundle(destination string) error {
	p, err := metadb.ResolvePaths("", "")
	if err != nil {
		return err
	}
	python := filepath.Join(destination, "runtime", ".venv", "bin", "python")
	cmd := exec.Command(python, "-I", "-c", `import pathlib,sqlite3,sys
from roami_agent.storage.migrations import SCHEMA_VERSION
p=pathlib.Path(sys.argv[1])
if p.exists():
 c=sqlite3.connect(p.as_uri()+"?mode=ro",uri=True)
 version=c.execute("SELECT max(version) FROM schema_meta").fetchone()[0]
 if version != SCHEMA_VERSION: raise SystemExit("AGENT_SCHEMA_UPGRADE_REQUIRES_OFFLINE_BACKUP: existing=%s candidate=%s" % (version,SCHEMA_VERSION))
`, filepath.Join(p.Database, "agents", "runtime.db"))
	cmd.Env = agentEnvironment()
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

func replaceAgentLink(target, name string) error {
	temporary, err := os.CreateTemp(filepath.Dir(name), ".roami-link-*")
	if err != nil {
		return err
	}
	temp := temporary.Name()
	temporary.Close()
	os.Remove(temp)
	defer os.Remove(temp)
	if err := os.Symlink(target, temp); err != nil {
		return err
	}
	return os.Rename(temp, name)
}

func activateAgentBundle(destination, binDir string) error {
	if binDir == "" {
		return fmt.Errorf("--bin-dir is required")
	}
	if _, err := os.Stat(filepath.Join(destination, "ready")); err != nil {
		return err
	}
	root := filepath.Dir(filepath.Dir(destination))
	if err := os.MkdirAll(binDir, 0755); err != nil {
		return err
	}
	current := filepath.Join(root, "current")
	oldCurrent, oldCurrentErr := os.Readlink(current)
	if old, err := os.Readlink(current); err == nil && old != destination {
		if err := replaceAgentLink(old, filepath.Join(root, "previous")); err != nil {
			return err
		}
	}
	entry := filepath.Join(binDir, "roami")
	if info, err := os.Lstat(entry); err == nil && info.Mode().IsRegular() {
		// Keep the original single-binary install until the replacement is usable.
		old, err := os.ReadFile(entry)
		if err != nil {
			return err
		}
		if err := os.WriteFile(filepath.Join(root, "previous-binary"), old, 0755); err != nil {
			return err
		}
	}
	if err := replaceAgentLink(destination, current); err != nil {
		return err
	}
	if err := replaceAgentLink(filepath.Join(root, "current", "bin", "roami"), entry); err != nil {
		if oldCurrentErr == nil {
			_ = replaceAgentLink(oldCurrent, current)
		} else if os.IsNotExist(oldCurrentErr) {
			_ = os.Remove(current)
		}
		return err
	}
	return nil
}
