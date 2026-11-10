package modelplugins

import (
	"context"
	"encoding/json"
	"io"
	"io/fs"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestEgressRejectsHostAndSpecialNetworks(t *testing.T) {
	for _, address := range []string{"127.0.0.1", "::1", "::ffff:127.0.0.1", "192.168.120.56", "10.0.0.1", "172.16.0.1", "169.254.169.254", "100.64.0.1", "198.18.0.1", "224.0.0.1", "0.0.0.0", "fc00::1", "fe80::1", "2001:db8::1", "64:ff9b::7f00:1", "2002:7f00:1::"} {
		if publicAddress(netip.MustParseAddr(address)) {
			t.Errorf("accepted %s", address)
		}
	}
	for _, address := range []string{"1.1.1.1", "8.8.8.8", "2606:4700:4700::1111"} {
		if !publicAddress(netip.MustParseAddr(address)) {
			t.Errorf("rejected %s", address)
		}
	}
}

// Opt in with the checked-out upstream fixture root; these calls never log in
// or issue a model request, and run the unmodified packages in the real jail.
func TestOfficialMagpiePackages(t *testing.T) {
	source := os.Getenv("ROAMI_MAGPIE_FIXTURES")
	if source == "" {
		t.Skip("set ROAMI_MAGPIE_FIXTURES to the pinned community packages directory")
	}
	bun := os.Getenv("ROAMI_MAGPIE_BUN")
	if bun == "" {
		t.Fatal("ROAMI_MAGPIE_BUN is required")
	}
	for _, name := range []string{"workbuddy", "doubao-work"} {
		t.Run(name, func(t *testing.T) {
			root := t.TempDir()
			runtimeDir := filepath.Join(root, "runtime")
			if err := MaterializeRuntime(runtimeDir); err != nil {
				t.Fatal(err)
			}
			var uploads []Upload
			err := filepath.WalkDir(filepath.Join(source, name), func(p string, d fs.DirEntry, err error) error {
				if err != nil {
					return err
				}
				if d.IsDir() {
					return nil
				}
				relative, _ := filepath.Rel(filepath.Join(source, name), p)
				if d.Type()&fs.ModeSymlink != 0 {
					return ErrInvalidPackage
				}
				data, err := os.ReadFile(p)
				if err != nil {
					return err
				}
				uploads = append(uploads, Upload{filepath.ToSlash(relative), strings.NewReader(string(data))})
				return nil
			})
			if err != nil {
				t.Fatal(err)
			}
			pkg, err := ImportFolder(filepath.Join(root, "packages"), uploads)
			if err != nil {
				t.Fatal(err)
			}
			if name == "doubao-work" && !trustedDoubaoDirectory(filepath.Join(root, "packages", pkg.ID)) {
				t.Fatal("official folder import lost desktop trust")
			}
			state := filepath.Join(root, "state")
			if err = os.Mkdir(state, 0700); err != nil {
				t.Fatal(err)
			}
			socket := filepath.Join(root, "egress.sock")
			egress, err := NewEgress(socket)
			if err != nil {
				t.Fatal(err)
			}
			defer egress.Close()
			command, err := SandboxCommand(SandboxPaths{Bun: bun, Runtime: runtimeDir, Package: filepath.Join(root, "packages", pkg.ID), State: state, EgressSocket: socket, Unit: "roami-model-plugin-test-" + name + "-" + pkg.ID[:8]})
			if err != nil {
				t.Fatal(err)
			}
			host, err := StartHost(command)
			if err != nil {
				t.Fatal(err)
			}
			defer host.Close()
			ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			defer cancel()
			var init struct {
				Plugins []struct {
					Error    string   `json:"error"`
					Provides []string `json:"provides"`
				} `json:"plugins"`
			}
			err = host.Call(ctx, "init", map[string]any{"authPath": "/state/auth.json", "directory": "/state", "piPath": "/runtime/host/magpie-pi.js", "plugins": []any{map[string]any{"spec": pkg.Name, "target": "/plugin"}}}, &init)
			if err != nil {
				t.Fatal(err)
			}
			if len(init.Plugins) != 1 || init.Plugins[0].Error != "" {
				t.Fatalf("init: %+v", init)
			}
			var providers []struct {
				ID             string            `json:"id"`
				Models         []json.RawMessage `json:"models"`
				MaxConcurrency int               `json:"maxConcurrency"`
				Methods        []json.RawMessage `json:"methods"`
			}
			if err = host.Call(ctx, "providers", map[string]any{}, &providers); err != nil {
				t.Fatal(err)
			}
			if name == "workbuddy" {
				if len(providers) != 2 {
					t.Fatalf("expected China and international providers: %+v", providers)
				}
			} else if len(providers) != 1 || providers[0].ID != "doubao-work" || providers[0].MaxConcurrency != 1 {
				t.Fatalf("unexpected Doubao provider: %+v", providers)
			}
			for _, p := range providers {
				if len(p.Models) == 0 || len(p.Methods) == 0 {
					t.Fatalf("missing models or login: %+v", p)
				}
			}
			t.Logf("%s %s: loaded %d providers with declared models and login methods", pkg.Name, pkg.Version, len(providers))
		})
	}
}

func TestMagpieStreamingIsolation(t *testing.T) {
	bun := os.Getenv("ROAMI_MAGPIE_BUN")
	if bun == "" {
		t.Skip("set ROAMI_MAGPIE_BUN for the real sandbox integration")
	}
	root := t.TempDir()
	runtimeDir := filepath.Join(root, "runtime")
	if err := MaterializeRuntime(runtimeDir); err != nil {
		t.Fatal(err)
	}
	script := `import fs from 'node:fs'; export const Probe=async()=>({config:async cfg=>{cfg.provider??={};cfg.provider.probe={name:'Probe',npm:'@ai-sdk/openai-compatible',api:'https://probe.invalid/v1',models:{probe:{name:'Probe'}}}},auth:{provider:'probe',methods:[{type:'api',label:'API Key'}],loader:async()=>({apiKey:'fixture',fetch:async()=>{if(fs.existsSync('/home')||fs.existsSync('/run/user'))throw Error('host filesystem exposed');let n=0;return new Response(new ReadableStream({pull(c){if(n++<32)c.enqueue(new TextEncoder().encode('x'.repeat(65536)));else c.close()}}),{headers:{'content-type':'text/plain'}})}})}})`
	pkg, err := ImportFolder(filepath.Join(root, "packages"), []Upload{{"package.json", strings.NewReader(`{"name":"probe","main":"index.mjs"}`)}, {"index.mjs", strings.NewReader(script)}})
	if err != nil {
		t.Fatal(err)
	}
	state := filepath.Join(root, "state")
	if err = os.Mkdir(state, 0700); err != nil {
		t.Fatal(err)
	}
	socket := filepath.Join(root, "egress.sock")
	egress, err := NewEgress(socket)
	if err != nil {
		t.Fatal(err)
	}
	defer egress.Close()
	command, err := SandboxCommand(SandboxPaths{Bun: bun, Runtime: runtimeDir, Package: filepath.Join(root, "packages", pkg.ID), State: state, EgressSocket: socket, Unit: "roami-model-plugin-test-stream-" + pkg.ID[:8]})
	if err != nil {
		t.Fatal(err)
	}
	host, err := StartHost(command)
	if err != nil {
		t.Fatal(err)
	}
	defer host.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err = host.Call(ctx, "init", map[string]any{"authPath": "/state/auth.json", "directory": "/state", "plugins": []any{map[string]any{"spec": pkg.Name, "target": "/plugin"}}}, nil); err != nil {
		t.Fatal(err)
	}
	if err = host.Call(ctx, "apiKey", map[string]any{"provider": "probe", "method": 0, "key": "fixture-test-only"}, nil); err != nil {
		t.Fatal(err)
	}
	response, err := host.Fetch(ctx, map[string]any{"provider": "probe", "model": "probe", "npm": "@ai-sdk/openai-compatible", "url": "https://probe.invalid/v1/chat/completions", "method": "POST", "body": "e30="})
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	// Keep a stream unread past its credit window while an unrelated RPC completes.
	time.Sleep(50 * time.Millisecond)
	var providers []json.RawMessage
	if err = host.Call(ctx, "providers", nil, &providers); err != nil {
		t.Fatal(err)
	}
	data, err := io.ReadAll(response.Body)
	if err != nil || len(data) != 32*65536 {
		t.Fatalf("stream lost bytes: %d %v", len(data), err)
	}
	slow, cancelSlow := context.WithCancel(ctx)
	next, err := host.Fetch(slow, map[string]any{"provider": "probe", "model": "probe", "url": "https://probe.invalid/v1/chat/completions", "method": "POST", "body": "e30="})
	if err != nil {
		t.Fatal(err)
	}
	cancelSlow()
	if _, err = io.ReadAll(next.Body); err == nil {
		t.Fatal("cancelled stream completed")
	}
	_ = next.Body.Close()
	if err = host.Call(ctx, "providers", nil, &providers); err != nil {
		t.Fatalf("cancelled stream blocked host: %v", err)
	}
}

func TestPublicEgressTLS(t *testing.T) {
	if os.Getenv("ROAMI_MAGPIE_NETWORK_TEST") != "1" {
		t.Skip("set ROAMI_MAGPIE_NETWORK_TEST=1 for public TLS egress")
	}
	socket := filepath.Join(t.TempDir(), "egress.sock")
	egress, err := NewEgress(socket)
	if err != nil {
		t.Fatal(err)
	}
	defer egress.Close()
	proxy, _ := url.Parse("http://plugin-egress.invalid:80")
	transport := &http.Transport{Proxy: http.ProxyURL(proxy), DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", socket)
	}}
	defer transport.CloseIdleConnections()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	request, _ := http.NewRequestWithContext(ctx, "HEAD", "https://example.com", nil)
	response, err := (&http.Client{Transport: transport}).Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		t.Fatalf("public TLS status %d", response.StatusCode)
	}
}
