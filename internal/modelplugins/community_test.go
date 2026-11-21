package modelplugins

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha512"
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type communityTransport func(*http.Request) (*http.Response, error)

func (fetch communityTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	return fetch(request)
}

func TestCommunityClientUsesSavedProxyAndHonorsProcessOverrides(t *testing.T) {
	for _, key := range []string{"HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy"} {
		t.Setenv(key, "")
	}
	env := []string{"https_proxy=http://saved.example:8080", "no_proxy=cdn.jsdelivr.net"}
	proxy := newCommunityClient(func() []string { return env }).Transport.(*http.Transport).Proxy
	check := func(target, want string) {
		t.Helper()
		request, err := http.NewRequest(http.MethodGet, target, nil)
		if err != nil {
			t.Fatal(err)
		}
		value, err := proxy(request)
		got := ""
		if value != nil {
			got = value.String()
		}
		if got != want || err != nil {
			t.Fatalf("proxy for %s = %q, %v; want %q", target, got, err, want)
		}
	}
	check(communityRaw, "http://saved.example:8080")
	check("https://cdn.jsdelivr.net/", "")
	env = []string{"HTTPS_PROXY=http://updated.example:8080"}
	check(communityRaw, "http://updated.example:8080")
	t.Setenv("https_proxy", "http://process.example:8080")
	check(communityRaw, "http://process.example:8080")
}

func TestCommunityCatalogSurvivesMissingReleaseIndex(t *testing.T) {
	const name = "@magpie-community/opencode-fixture-auth"
	manager := &Manager{communityHTTP: &http.Client{Transport: communityTransport(func(r *http.Request) (*http.Response, error) {
		if strings.HasSuffix(r.URL.Path, "/index.json") {
			deadline, ok := r.Context().Deadline()
			if !ok || time.Until(deadline) <= 8*time.Second {
				t.Error("release index inherited the small-request deadline")
			}
			return &http.Response{StatusCode: http.StatusServiceUnavailable, Body: http.NoBody}, nil
		}
		registry := `{"version":1,"plugins":[{"package":"` + name + `","name":"Fixture","providers":["fixture"],"version":"unverified"}]}`
		return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(strings.NewReader(registry))}, nil
	})}}
	plugins, err := manager.CommunityPlugins(context.Background(), "github")
	if err != nil || len(plugins) != 1 || plugins[0].Package != name || plugins[0].Version != "" {
		t.Fatalf("directory without release index: %+v, %v", plugins, err)
	}
}

func TestCommunityImportUsesRegistryAndChecksMirroredPackage(t *testing.T) {
	const name = "@magpie-community/opencode-fixture-auth"
	const version = "1.2.3"
	const file = "tgz/magpie-community-opencode-fixture-auth-1.2.3.tgz"
	registry := `{"version":1,"plugins":[{"package":"` + name + `","name":"Fixture","providers":["fixture"]},{"package":"@magpie-community/tools-fixture","name":"Fixture Tools","kind":"tool"}]}`
	var buffer bytes.Buffer
	compressed := gzip.NewWriter(&buffer)
	archive := tar.NewWriter(compressed)
	for filename, content := range map[string]string{
		"package/package.json": `{"name":"` + name + `","version":"` + version + `","main":"index.mjs"}`,
		"package/index.mjs":    "export default async () => ({})",
	} {
		if err := archive.WriteHeader(&tar.Header{Name: filename, Mode: 0644, Size: int64(len(content))}); err != nil {
			t.Fatal(err)
		}
		if _, err := io.WriteString(archive, content); err != nil {
			t.Fatal(err)
		}
	}
	if err := archive.Close(); err != nil {
		t.Fatal(err)
	}
	if err := compressed.Close(); err != nil {
		t.Fatal(err)
	}
	sum := sha512.Sum512(buffer.Bytes())
	index := fmt.Sprintf(`{"version":1,"packages":{%q:{"latest":%q,"versions":{%q:{"file":%q,"integrity":"sha512-%s"}}}}}`, name, version, version, file, base64.StdEncoding.EncodeToString(sum[:]))

	var requested []string
	officialAvailable := true
	client := &http.Client{Transport: communityTransport(func(r *http.Request) (*http.Response, error) {
		if r.Header.Get("Authorization") != "" || r.Header.Get("Cookie") != "" {
			t.Fatal("credentials sent to a public plugin feed")
		}
		requested = append(requested, r.URL.Host)
		data, status := "", http.StatusOK
		switch {
		case strings.HasSuffix(r.URL.Path, "/registry.json"):
			data = registry
		case strings.HasSuffix(r.URL.Path, "/index.json"):
			data = index
		case strings.HasSuffix(r.URL.Path, "/"+file):
			if r.URL.Host != "raw.githubusercontent.com" || !officialAvailable {
				data = "corrupt tarball"
			} else {
				data = buffer.String()
			}
		default:
			status = http.StatusNotFound
		}
		return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader(data))}, nil
	})}
	ctx := context.Background()
	rows, err := communityProviders(ctx, client, "china")
	if err != nil || len(rows) != 1 || rows[0].Package != name || requested[0] != "cdn.jsdelivr.net" {
		t.Fatalf("community provider directory: %+v %v %v", rows, err, requested)
	}
	root := t.TempDir()
	requested = nil
	pkg, err := importCommunity(ctx, client, root, "gh-hk", name, version)
	if err != nil || pkg.Name != name || pkg.Version != version || pkg.Entry != "index.mjs" {
		t.Fatalf("community import: %+v %v", pkg, err)
	}
	if strings.Join(requested, " ") != "hk.gh-proxy.org raw.githubusercontent.com hk.gh-proxy.org gh-proxy.com raw.githubusercontent.com" {
		t.Fatal("unexpected mirror order", requested)
	}
	if _, err := os.Stat(filepath.Join(root, pkg.ID, pkg.Entry)); err != nil {
		t.Fatal(err)
	}
	officialAvailable = false
	rejected := t.TempDir()
	if _, err := importCommunity(ctx, client, rejected, "china", name, version); err != ErrCommunityIntegrity {
		t.Fatal("corrupted package accepted", err)
	}
	if entries, _ := os.ReadDir(rejected); len(entries) != 0 {
		t.Fatal("a corrupt package was persisted")
	}
	if _, err := importCommunity(ctx, client, root, "github", "@magpie-community/tools-fixture", version); err != ErrInvalidPackage {
		t.Fatal("a tools plugin was accepted as a model source", err)
	}
}
