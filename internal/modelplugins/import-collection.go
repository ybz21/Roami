package modelplugins

import (
	"encoding/json"
	"errors"
	"path"
	"sort"
	"strings"
)

const MaxPackages = 128

type Collection struct {
	Packages []Package `json:"packages"`
	Skipped  []string  `json:"skipped,omitempty"`
}

func collectionMetadata(name string) bool {
	for _, part := range strings.Split(name, "/") {
		if part == ".git" || part == "node_modules" || part == ".env" || strings.HasPrefix(part, ".env.") {
			return true
		}
	}
	return false
}

func packageFiles(files map[string][]byte, dir string) map[string][]byte {
	result := map[string][]byte{}
	prefix := ""
	if dir != "." {
		prefix = dir + "/"
	}
	for name, data := range files {
		if strings.HasPrefix(name, prefix) {
			result[strings.TrimPrefix(name, prefix)] = data
		}
	}
	return result
}

// Workspace manifests discover packages; importing never executes their scripts.
func ImportCollectionFolder(root string, uploads []Upload) (Collection, error) {
	files, err := readUploadFiles(uploads, true)
	if err != nil {
		return Collection{}, err
	}
	manifests := []string{}
	for name := range files {
		if path.Base(name) == "package.json" {
			manifests = append(manifests, name)
		}
	}
	sort.Strings(manifests)
	result := Collection{Packages: []Package{}}
	roots := []string{}
	for _, filename := range manifests {
		var m manifest
		if json.Unmarshal(files[filename], &m) != nil {
			result.Skipped = append(result.Skipped, filename)
			continue
		}
		var workspace struct {
			Workspaces json.RawMessage `json:"workspaces"`
		}
		_ = json.Unmarshal(files[filename], &workspace)
		if len(workspace.Workspaces) > 0 && string(workspace.Workspaces) != "null" {
			continue
		}
		dir := path.Dir(filename)
		candidates := packageFiles(files, dir)
		if _, err := packageEntry(m, candidates); err != nil {
			if m.Main != "" || len(m.Exports) > 0 {
				result.Skipped = append(result.Skipped, filename)
			}
			continue
		}
		if m.Magpie.MaxConcurrency < 0 || m.Magpie.MaxConcurrency > 128 || m.Name == "" || len(m.Name) > 200 || len(m.Version) > 100 || strings.ContainsAny(m.Name+m.Version, "\r\n\x00") {
			result.Skipped = append(result.Skipped, filename)
			continue
		}
		roots = append(roots, dir)
		if len(roots) > MaxPackages {
			return Collection{}, ErrInvalidPackage
		}
	}
	// A nested plugin belongs to its own package rather than its ancestor.
	sort.Slice(roots, func(i, j int) bool {
		if len(roots[i]) == len(roots[j]) {
			return roots[i] < roots[j]
		}
		return len(roots[i]) > len(roots[j])
	})
	groups := make(map[string]map[string][]byte, len(roots))
	for _, dir := range roots {
		groups[dir] = map[string][]byte{}
	}
	for name, data := range files {
		for _, dir := range roots {
			prefix := ""
			if dir != "." {
				prefix = dir + "/"
			}
			if strings.HasPrefix(name, prefix) {
				groups[dir][strings.TrimPrefix(name, prefix)] = data
				break
			}
		}
	}
	sort.Strings(roots)
	seen := map[string]bool{}
	for _, dir := range roots {
		pkg, err := importPackageFiles(root, groups[dir])
		if errors.Is(err, ErrInvalidPackage) {
			result.Skipped = append(result.Skipped, path.Join(dir, "package.json"))
			continue
		}
		if err != nil {
			return Collection{}, err
		}
		if !seen[pkg.ID] {
			result.Packages = append(result.Packages, pkg)
			seen[pkg.ID] = true
		}
	}
	if len(result.Packages) == 0 {
		return Collection{}, ErrInvalidPackage
	}
	sort.Strings(result.Skipped)
	return result, nil
}
