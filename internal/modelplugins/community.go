package modelplugins

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha512"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"regexp"
	"strings"
	"sync"
	"time"
)

const communityRepo = "magpie-community/plugins"
const communityRaw = "https://raw.githubusercontent.com/" + communityRepo + "/"

var (
	ErrCommunityUnavailable = errors.New("MODEL_PLUGIN_COMMUNITY_UNAVAILABLE")
	ErrCommunityIntegrity   = errors.New("MODEL_PLUGIN_COMMUNITY_INTEGRITY")
	communityName           = regexp.MustCompile(`^@magpie-community/[a-z0-9][a-z0-9._-]{0,119}$`)
	communityArchive        = regexp.MustCompile(`^tgz/[a-zA-Z0-9._+-]+\.tgz$`)
)

type CommunityPlugin struct {
	Package   string   `json:"package"`
	Name      string   `json:"name"`
	Providers []string `json:"providers"`
	Version   string   `json:"version"`
}

type communityRelease struct {
	File      string `json:"file"`
	Integrity string `json:"integrity"`
}

type communityIndex struct {
	Version  int `json:"version"`
	Packages map[string]struct {
		Latest   string                      `json:"latest"`
		Versions map[string]communityRelease `json:"versions"`
	} `json:"packages"`
}

func ValidCommunityChannel(channel string) bool {
	return channel == "" || channel == "github" || channel == "china" || channel == "gh-hk"
}

func communityURLs(channel, branch, file string) []string {
	official := communityRaw + branch + "/" + file
	var mirrors []string
	switch channel {
	case "china":
		mirrors = []string{"https://cdn.jsdelivr.net/gh/" + communityRepo + "@" + branch + "/" + file}
	case "gh-hk":
		mirrors = []string{"https://hk.gh-proxy.org/" + official, "https://gh-proxy.com/" + official}
	}
	if branch == "dist" && file == "index.json" {
		return append([]string{official}, mirrors...)
	}
	return append(mirrors, official)
}

var communityHTTP = &http.Client{
	Timeout: 8 * time.Second,
	CheckRedirect: func(next *http.Request, via []*http.Request) error {
		if len(via) >= 3 || next.URL.Scheme != "https" || next.URL.Host != via[0].URL.Host {
			return http.ErrUseLastResponse
		}
		return nil
	},
}

func readCommunity(ctx context.Context, client *http.Client, channel, branch, file string, limit int64, accept func([]byte) error) error {
	err := ErrCommunityUnavailable
	for _, endpoint := range communityURLs(channel, branch, file) {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		timeout := 8 * time.Second
		if strings.HasSuffix(file, ".json") {
			timeout = 4 * time.Second
		}
		attempt, cancel := context.WithTimeout(ctx, timeout)
		req, requestErr := http.NewRequestWithContext(attempt, http.MethodGet, endpoint, nil)
		if requestErr != nil {
			cancel()
			return ErrCommunityUnavailable
		}
		response, requestErr := client.Do(req)
		if requestErr != nil {
			cancel()
			continue
		}
		if response.StatusCode != http.StatusOK {
			response.Body.Close()
			cancel()
			continue
		}
		data, readErr := io.ReadAll(io.LimitReader(response.Body, limit+1))
		response.Body.Close()
		cancel()
		if readErr != nil || int64(len(data)) > limit {
			continue
		}
		if invalid := accept(data); invalid == nil {
			return nil
		} else {
			err = invalid
		}
	}
	return err
}

func communityProviders(ctx context.Context, client *http.Client, channel string) ([]CommunityPlugin, error) {
	var registry struct {
		Version int               `json:"version"`
		Plugins []CommunityPlugin `json:"plugins"`
	}
	err := readCommunity(ctx, client, channel, "main", "registry.json", 1<<20, func(data []byte) error {
		registry.Plugins = nil
		if json.Unmarshal(data, &registry) != nil || registry.Version != 1 || registry.Plugins == nil {
			return ErrCommunityUnavailable
		}
		return nil
	})
	plugins := []CommunityPlugin{}
	seen := map[string]bool{}
	for _, plugin := range registry.Plugins {
		if len(plugin.Providers) > 0 && communityName.MatchString(plugin.Package) && !seen[plugin.Package] {
			plugins = append(plugins, plugin)
			seen[plugin.Package] = true
		}
	}
	return plugins, err
}

func communityReleases(ctx context.Context, client *http.Client, channel string) (communityIndex, error) {
	var index communityIndex
	err := readCommunity(ctx, client, channel, "dist", "index.json", MaxFileBytes, func(data []byte) error {
		index = communityIndex{}
		if json.Unmarshal(data, &index) != nil || index.Version != 1 || index.Packages == nil {
			return ErrCommunityUnavailable
		}
		return nil
	})
	return index, err
}

func (m *Manager) CommunityPlugins(ctx context.Context, channel string) ([]CommunityPlugin, error) {
	var index communityIndex
	var indexErr error
	var pending sync.WaitGroup
	pending.Add(1)
	go func() {
		defer pending.Done()
		index, indexErr = communityReleases(ctx, communityHTTP, channel)
	}()
	plugins, err := communityProviders(ctx, communityHTTP, channel)
	pending.Wait()
	if err != nil {
		return nil, err
	}
	if indexErr != nil {
		return nil, indexErr
	}
	for i := range plugins {
		published := index.Packages[plugins[i].Package]
		if published.Versions[published.Latest].File != "" {
			plugins[i].Version = published.Latest
		}
	}
	return plugins, nil
}

func (m *Manager) ImportCommunity(ctx context.Context, channel, name, version string) (Package, error) {
	return importCommunity(ctx, communityHTTP, m.PackagesRoot(), channel, name, version)
}

func importCommunity(ctx context.Context, client *http.Client, root, channel, name, version string) (Package, error) {
	if !communityName.MatchString(name) || version == "" || len(version) > 100 {
		return Package{}, ErrInvalidPackage
	}
	plugins, err := communityProviders(ctx, client, channel)
	if err != nil {
		return Package{}, err
	}
	allowed := false
	for _, plugin := range plugins {
		if plugin.Package == name {
			allowed = true
			break
		}
	}
	if !allowed {
		return Package{}, ErrInvalidPackage
	}
	index, err := communityReleases(ctx, client, channel)
	if err != nil {
		return Package{}, err
	}
	release := index.Packages[name].Versions[version]
	if !communityArchive.MatchString(release.File) || !strings.HasPrefix(release.Integrity, "sha512-") {
		return Package{}, ErrInvalidPackage
	}
	hash, err := base64.StdEncoding.DecodeString(strings.TrimPrefix(release.Integrity, "sha512-"))
	if err != nil || len(hash) != sha512.Size {
		return Package{}, ErrInvalidPackage
	}
	var files map[string][]byte
	err = readCommunity(ctx, client, channel, "dist", release.File, MaxArchiveBytes, func(data []byte) error {
		sum := sha512.Sum512(data)
		if !bytes.Equal(sum[:], hash) {
			return ErrCommunityIntegrity
		}
		var err error
		files, err = readCommunityPackage(data, name, version)
		return err
	})
	if err != nil {
		return Package{}, err
	}
	return importPackageFiles(root, files)
}

func readCommunityPackage(data []byte, name, version string) (map[string][]byte, error) {
	reader, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return nil, ErrInvalidPackage
	}
	defer reader.Close()
	archive := tar.NewReader(io.LimitReader(reader, MaxExpandedBytes+4*MaxFiles*512))
	files := map[string][]byte{}
	var total int64
	for count := 0; ; count++ {
		entry, err := archive.Next()
		if err == io.EOF {
			break
		}
		if err != nil || count >= MaxFiles {
			return nil, ErrInvalidPackage
		}
		if entry.Typeflag == tar.TypeDir && strings.TrimSuffix(entry.Name, "/") == "package" {
			continue
		}
		file, underPackage := strings.CutPrefix(strings.TrimSuffix(entry.Name, "/"), "package/")
		if _, err := relativeName(file); !underPackage || err != nil || file == ".roami-package.json" {
			return nil, ErrInvalidPackage
		}
		if entry.Typeflag == tar.TypeDir {
			continue
		}
		if _, duplicate := files[file]; duplicate || entry.Typeflag != tar.TypeReg || entry.Size < 0 || entry.Size > MaxFileBytes || total+entry.Size > MaxExpandedBytes {
			return nil, ErrInvalidPackage
		}
		content, err := io.ReadAll(io.LimitReader(archive, MaxFileBytes+1))
		if err != nil || int64(len(content)) != entry.Size {
			return nil, ErrInvalidPackage
		}
		total += entry.Size
		files[file] = content
	}
	var packageManifest manifest
	if json.Unmarshal(files["package.json"], &packageManifest) != nil || packageManifest.Name != name || packageManifest.Version != version {
		return nil, ErrInvalidPackage
	}
	return files, nil
}
