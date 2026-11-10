// Package modelplugins imports immutable Magpie provider packages.
package modelplugins

import (
	"archive/zip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
)

const MaxArchiveBytes = 32 << 20
const MaxExpandedBytes = 64 << 20
const MaxFiles = 2048
const MaxFileBytes = 16 << 20

var ErrInvalidPackage = errors.New("INVALID_MODEL_PLUGIN_PACKAGE")

// Upload paths are relative to the directory selected by the user.
type Upload struct {
	Path   string
	Reader io.Reader
}
type Package struct {
	ID             string `json:"id"`
	Name           string `json:"name"`
	Version        string `json:"version"`
	Entry          string `json:"entry"`
	MaxConcurrency int    `json:"maxConcurrency,omitempty"`
}
type manifest struct {
	Name    string          `json:"name"`
	Version string          `json:"version"`
	Main    string          `json:"main"`
	Exports json.RawMessage `json:"exports"`
	Magpie  struct {
		MaxConcurrency int `json:"maxConcurrency"`
	} `json:"magpie"`
}

func relativeName(name string) (string, error) {
	if name == "" || len(name) > 1024 || strings.ContainsAny(name, "\\\x00:") || strings.HasPrefix(name, "/") || path.Clean(name) != name || name == "." || name == ".." || strings.HasPrefix(name, "../") {
		return "", ErrInvalidPackage
	}
	for _, part := range strings.Split(name, "/") {
		if part == ".git" || part == ".env" || strings.HasPrefix(part, ".env.") {
			return "", ErrInvalidPackage
		}
	}
	return name, nil
}

// ImportZIP and ImportFolder share validation and the same content-addressed layout.
func ImportZIP(root string, input io.ReaderAt, size int64) (Package, error) {
	if size <= 0 || size > MaxArchiveBytes {
		return Package{}, ErrInvalidPackage
	}
	z, err := zip.NewReader(input, size)
	if err != nil {
		return Package{}, ErrInvalidPackage
	}
	if len(z.File) > MaxFiles {
		return Package{}, ErrInvalidPackage
	}
	uploads := make([]Upload, 0, len(z.File))
	readers := []io.Closer{}
	defer func() {
		for _, r := range readers {
			_ = r.Close()
		}
	}()
	for _, f := range z.File {
		if f.Mode()&(fs.ModeSymlink|fs.ModeDevice|fs.ModeNamedPipe|fs.ModeSocket) != 0 || f.Flags&1 != 0 {
			return Package{}, ErrInvalidPackage
		}
		name := strings.TrimSuffix(f.Name, "/")
		if _, err := relativeName(name); err != nil {
			return Package{}, err
		}
		if archiveMetadata(name) {
			continue
		}
		if f.FileInfo().IsDir() {
			continue
		}
		if f.UncompressedSize64 > MaxFileBytes {
			return Package{}, ErrInvalidPackage
		}
		r, err := f.Open()
		if err != nil {
			return Package{}, ErrInvalidPackage
		}
		readers = append(readers, r)
		uploads = append(uploads, Upload{name, r})
	}
	return ImportFolder(root, uploads)
}

func ImportFolder(root string, uploads []Upload) (Package, error) {
	if len(uploads) == 0 || len(uploads) > MaxFiles {
		return Package{}, ErrInvalidPackage
	}
	files := make(map[string][]byte, len(uploads))
	total := 0
	for _, file := range uploads {
		name, err := relativeName(file.Path)
		if err != nil || file.Reader == nil {
			return Package{}, ErrInvalidPackage
		}
		if archiveMetadata(name) {
			continue
		}
		if name == ".roami-package.json" || strings.HasSuffix(name, "/.roami-package.json") {
			return Package{}, ErrInvalidPackage
		}
		if _, exists := files[name]; exists {
			return Package{}, ErrInvalidPackage
		}
		data, err := io.ReadAll(io.LimitReader(file.Reader, MaxFileBytes+1))
		if err != nil || len(data) > MaxFileBytes {
			return Package{}, ErrInvalidPackage
		}
		total += len(data)
		if total > MaxExpandedBytes {
			return Package{}, ErrInvalidPackage
		}
		files[name] = data
	}
	// A selected folder and a ZIP may contain their single enclosing directory.
	if _, ok := files["package.json"]; !ok {
		prefix := ""
		for name := range files {
			first, _, found := strings.Cut(name, "/")
			if !found {
				return Package{}, ErrInvalidPackage
			}
			if prefix == "" {
				prefix = first + "/"
			}
			if !strings.HasPrefix(name, prefix) {
				return Package{}, ErrInvalidPackage
			}
		}
		stripped := make(map[string][]byte, len(files))
		for name, data := range files {
			stripped[strings.TrimPrefix(name, prefix)] = data
		}
		files = stripped
	}
	var m manifest
	if json.Unmarshal(files["package.json"], &m) != nil || m.Name == "" || len(m.Name) > 200 || len(m.Version) > 100 || strings.ContainsAny(m.Name+m.Version, "\r\n\x00") {
		return Package{}, ErrInvalidPackage
	}

	entry, err := packageEntry(m, files)
	if err != nil {
		return Package{}, err
	}

	names := make([]string, 0, len(files))
	for name := range files {
		names = append(names, name)
	}
	sort.Strings(names)
	hash := sha256.New()
	for _, name := range names {
		fmt.Fprintf(hash, "%d:%s:%d:", len(name), name, len(files[name]))
		hash.Write(files[name])
	}
	pkg := Package{ID: hex.EncodeToString(hash.Sum(nil)), Name: m.Name, Version: m.Version, Entry: entry, MaxConcurrency: m.Magpie.MaxConcurrency}
	if pkg.MaxConcurrency < 0 || pkg.MaxConcurrency > 128 {
		return Package{}, ErrInvalidPackage
	}
	if err := os.MkdirAll(root, 0700); err != nil {
		return Package{}, err
	}
	staging, err := os.MkdirTemp(root, ".import-")
	if err != nil {
		return Package{}, err
	}
	defer os.RemoveAll(staging)
	for _, name := range names {
		dest := filepath.Join(staging, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(dest), 0700); err != nil {
			return Package{}, err
		}
		if err := os.WriteFile(dest, files[name], 0600); err != nil {
			return Package{}, err
		}
	}
	metadata, _ := json.Marshal(pkg)
	if err := os.WriteFile(filepath.Join(staging, ".roami-package.json"), metadata, 0600); err != nil {
		return Package{}, err
	}
	destination := filepath.Join(root, pkg.ID)
	if err := os.Rename(staging, destination); err != nil {
		// Only reuse a package with identical validated metadata; never overwrite it.
		stored, readErr := os.ReadFile(filepath.Join(destination, ".roami-package.json"))
		if readErr != nil || string(stored) != string(metadata) {
			return Package{}, err
		}
	}
	return pkg, nil
}

func archiveMetadata(name string) bool {
	return path.Base(name) == ".DS_Store" || name == "__MACOSX" || strings.HasPrefix(name, "__MACOSX/")
}
func packageEntry(m manifest, files map[string][]byte) (string, error) {
	candidates := []string{}
	add := func(value string) {
		if strings.TrimSpace(value) != "" {
			candidates = append(candidates, strings.TrimPrefix(strings.TrimSpace(value), "./"))
		}
	}
	pick := func(raw json.RawMessage) string {
		var text string
		if json.Unmarshal(raw, &text) == nil {
			return text
		}
		var condition struct {
			Import  string `json:"import"`
			Default string `json:"default"`
		}
		if json.Unmarshal(raw, &condition) == nil {
			if condition.Import != "" {
				return condition.Import
			}
			return condition.Default
		}
		return ""
	}
	var exports map[string]json.RawMessage
	if json.Unmarshal(m.Exports, &exports) == nil {
		add(pick(exports["./server"]))
	}
	add(m.Main)
	if exports != nil {
		add(pick(exports["."]))
	} else {
		add(pick(m.Exports))
	}
	candidates = append(candidates, "index.ts", "index.tsx", "index.js", "index.mjs", "index.cjs")
	entry := ""
	for _, candidate := range candidates {
		if _, err := relativeName(candidate); err != nil {
			return "", err
		}
		if _, exists := files[candidate]; !exists {
			continue
		}
		ext := path.Ext(candidate)
		if ext != ".mjs" && ext != ".js" && ext != ".cjs" && ext != ".ts" && ext != ".tsx" {
			return "", ErrInvalidPackage
		}
		if entry == "" {
			entry = candidate
		}
	}
	if entry == "" {
		return "", ErrInvalidPackage
	}
	return entry, nil
}
