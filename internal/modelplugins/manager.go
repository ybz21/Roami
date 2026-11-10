package modelplugins

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sync"
	"time"
)

var packageID = regexp.MustCompile(`^[a-f0-9]{64}$`)
var sourceID = regexp.MustCompile(`^[a-f0-9]{32}$`)

type Model struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	NPM       string `json:"npm"`
	URL       string `json:"url"`
	APIID     string `json:"apiId"`
	Context   int    `json:"context"`
	Output    int    `json:"output"`
	Reasoning bool   `json:"reasoning"`
	Image     bool   `json:"image"`
}
type AuthMethod struct {
	Keyless     bool              `json:"keyless,omitempty"`
	Placeholder string            `json:"placeholder,omitempty"`
	Labels      map[string]string `json:"labels,omitempty"`
	Type        string            `json:"type"`
	Label       string            `json:"label"`
}
type Provider struct {
	ID             string          `json:"id"`
	Name           string          `json:"name"`
	NPM            string          `json:"npm"`
	API            string          `json:"api"`
	Methods        []AuthMethod    `json:"methods"`
	Options        json.RawMessage `json:"options"`
	Models         []Model         `json:"models"`
	SignedIn       bool            `json:"signedIn"`
	MaxConcurrency int             `json:"maxConcurrency"`
	FellBack       bool            `json:"fellBack"`
}
type Source struct {
	ID         string         `json:"id"`
	PackageID  string         `json:"packageId"`
	ProviderID string         `json:"providerId"`
	Options    map[string]any `json:"options,omitempty"`
}
type worker struct {
	configMu      sync.Mutex
	configuration string
	host          *Host
	egress        *Egress
	runDir        string
	ready         chan struct{}
	err           error
	gate          chan struct{}
}
type Manager struct {
	AuthChanged func(string) error
	Root        string
	bun         string
	mu          sync.Mutex
	workers     map[string]*worker
	closed      bool
	jobs        map[string]*authJob
}

func NewManager(root string) (*Manager, error) {
	if err := os.MkdirAll(root, 0700); err != nil {
		return nil, err
	}
	bun, err := exec.LookPath("bun")
	if err != nil {
		home, _ := os.UserHomeDir()
		candidate := filepath.Join(home, ".bun", "bin", "bun")
		if info, e := os.Stat(candidate); e == nil && info.Mode().IsRegular() {
			bun = candidate
		}
	}
	if err := MaterializeRuntime(filepath.Join(root, "runtime")); err != nil {
		return nil, err
	}
	return &Manager{Root: root, bun: bun, workers: map[string]*worker{}, jobs: map[string]*authJob{}}, nil
}
func (m *Manager) PackagesRoot() string { return filepath.Join(m.Root, "packages") }
func (m *Manager) ReadPackage(id string) (Package, error) {
	if !packageID.MatchString(id) {
		return Package{}, ErrInvalidPackage
	}
	data, err := os.ReadFile(filepath.Join(m.PackagesRoot(), id, ".roami-package.json"))
	if err != nil {
		return Package{}, ErrInvalidPackage
	}
	var p Package
	if json.Unmarshal(data, &p) != nil || p.ID != id {
		return Package{}, ErrInvalidPackage
	}
	return p, nil
}
func (m *Manager) ReadSource(id string) (Source, error) {
	if !sourceID.MatchString(id) {
		return Source{}, ErrInvalidPackage
	}
	data, err := os.ReadFile(filepath.Join(m.Root, "sources", id, "source.json"))
	if err != nil {
		return Source{}, ErrInvalidPackage
	}
	var s Source
	if json.Unmarshal(data, &s) != nil || s.ID != id || s.ProviderID == "" {
		return Source{}, ErrInvalidPackage
	}
	if _, err = m.ReadPackage(s.PackageID); err != nil {
		return Source{}, err
	}
	return s, nil
}
func freshID() (string, error) {
	var bytes [16]byte
	_, err := rand.Read(bytes[:])
	return hex.EncodeToString(bytes[:]), err
}
func (m *Manager) save(s Source) error {
	state := filepath.Join(m.Root, "sources", s.ID)
	if err := os.MkdirAll(filepath.Join(state, "work"), 0700); err != nil {
		return err
	}
	data, err := json.Marshal(s)
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(state, ".source-")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	_, err = f.Write(data)
	if err == nil {
		err = f.Sync()
	}
	if closeErr := f.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	return os.Rename(f.Name(), filepath.Join(state, "source.json"))
}
func (m *Manager) Create(ctx context.Context, pkgID, providerID string) (Source, Provider, error) {
	if _, err := m.ReadPackage(pkgID); err != nil {
		return Source{}, Provider{}, err
	}
	id, err := freshID()
	if err != nil {
		return Source{}, Provider{}, err
	}
	s := Source{ID: id, PackageID: pkgID, ProviderID: providerID}
	if err = m.save(s); err != nil {
		return Source{}, Provider{}, err
	}
	provider, err := m.Provider(ctx, s)
	if err != nil {
		m.remove(s)
		return Source{}, Provider{}, err
	}
	return s, provider, nil
}
func (m *Manager) Inspect(ctx context.Context, pkgID string) ([]Provider, error) {
	if _, err := m.ReadPackage(pkgID); err != nil {
		return nil, err
	}
	id, err := freshID()
	if err != nil {
		return nil, err
	}
	s := Source{ID: id, PackageID: pkgID}
	if err = m.save(s); err != nil {
		return nil, err
	}
	defer m.remove(s)
	w, err := m.getWorker(ctx, s)
	if err != nil {
		return nil, err
	}
	var providers []Provider
	err = w.host.Call(ctx, "providers", nil, &providers)
	return providers, err
}
func (m *Manager) getWorker(ctx context.Context, s Source) (*worker, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	m.mu.Lock()
	if m.closed {
		m.mu.Unlock()
		return nil, ErrHostClosed
	}
	w := m.workers[s.ID]
	if w != nil {
		select {
		case <-w.hostDone():
			delete(m.workers, s.ID)
			w.close()
			w = nil
		default:
		}
	}
	if w == nil {
		if len(m.workers) >= 8 {
			m.mu.Unlock()
			return nil, errors.New("MODEL_PLUGIN_BUSY")
		}
		w = &worker{ready: make(chan struct{}), gate: make(chan struct{}, 1)}
		m.workers[s.ID] = w
		go func() { w.err = m.launch(s, w); close(w.ready) }()
	}
	m.mu.Unlock()
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-w.ready:
		if w.err != nil {
			m.mu.Lock()
			if m.workers[s.ID] == w {
				delete(m.workers, s.ID)
			}
			m.mu.Unlock()
			w.close()
			return nil, w.err
		}
		if err := m.synchronizeOptions(ctx, s, w); err != nil {
			return nil, err
		}
		return w, nil
	}
}
func (w *worker) hostDone() <-chan struct{} {
	select {
	case <-w.ready:
		if w.host != nil {
			return w.host.done
		}
	default:
	}
	return nil
}
func (w *worker) close() {
	<-w.ready
	if w.host != nil {
		_ = w.host.Close()
	}
	if w.egress != nil {
		_ = w.egress.Close()
	}
	if w.runDir != "" {
		_ = os.RemoveAll(w.runDir)
	}
}
func (m *Manager) launch(s Source, w *worker) error {
	if m.bun == "" {
		return errors.New("MODEL_PLUGIN_BUN_UNAVAILABLE")
	}
	pkg, err := m.ReadPackage(s.PackageID)
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Join(m.Root, "sources", s.ID, "work"), 0700); err != nil {
		return err
	}

	paths := SandboxPaths{Bun: m.bun, Runtime: filepath.Join(m.Root, "runtime"), Package: filepath.Join(m.PackagesRoot(), pkg.ID), State: filepath.Join(m.Root, "sources", s.ID, "work")}
	authPath, directory, piPath, target := "/state/auth.json", "/state", "/runtime/host/magpie-pi.js", "/plugin"
	var command *exec.Cmd
	if runtime.GOOS == "darwin" || runtime.GOOS == "windows" {
		if pkg.Name != "@magpie-community/opencode-doubao-work-auth" {
			return errors.New("MODEL_PLUGIN_SANDBOX_UNAVAILABLE")
		}
		home, _ := os.UserHomeDir()
		command, err = desktopCommand(paths, runtime.GOOS, home, os.Getenv("LOCALAPPDATA"))
		authPath = filepath.Join(paths.State, "auth.json")
		directory = paths.State
		piPath = filepath.Join(paths.Runtime, "magpie-pi.js")
		target = paths.Package
	} else {
		w.runDir, err = os.MkdirTemp("", "roami-model-plugin-")
		if err != nil {
			return err
		}
		paths.EgressSocket = filepath.Join(w.runDir, "egress.sock")
		w.egress, err = NewEgress(paths.EgressSocket)
		if err != nil {
			return err
		}
		unit, e := freshID()
		if e != nil {
			return e
		}
		paths.Unit = "roami-model-plugin-" + unit
		command, err = SandboxCommand(paths)
	}
	if err != nil {
		return err
	}
	w.host, err = StartHost(command)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	var result struct {
		Plugins []struct {
			Error string `json:"error"`
		} `json:"plugins"`
	}
	err = w.host.Call(ctx, "init", map[string]any{"authPath": authPath, "directory": directory, "piPath": piPath, "loadMillis": 20000, "listMillis": 15000, "options": map[string]any{s.ProviderID: s.Options}, "plugins": []any{map[string]any{"spec": pkg.Name, "target": target}}}, &result)
	if err != nil {
		return err
	}
	if len(result.Plugins) != 1 || result.Plugins[0].Error != "" {
		return errors.New("MODEL_PLUGIN_LOAD_FAILED")
	}
	return nil
}
func (m *Manager) Provider(ctx context.Context, s Source) (Provider, error) {
	w, err := m.getWorker(ctx, s)
	if err != nil {
		return Provider{}, err
	}
	var providers []Provider
	if err = w.host.Call(ctx, "providers", nil, &providers); err != nil {
		return Provider{}, err
	}
	for _, p := range providers {
		if p.ID == s.ProviderID {
			if !p.FellBack {
				m.mu.Lock()
				current, readErr := m.ReadSource(s.ID)
				before, _ := json.Marshal(s.Options)
				after, _ := json.Marshal(current.Options)
				if readErr != nil || string(before) != string(after) {
					m.mu.Unlock()
					return Provider{}, errors.New("MODEL_PLUGIN_MODELS_REQUIRED")
				}
				err := m.persistProvider(s, p)
				m.mu.Unlock()
				if err != nil {
					return Provider{}, err
				}
			}
			return p, nil
		}
	}
	return Provider{}, errors.New("MODEL_PLUGIN_PROVIDER_NOT_FOUND")
}
func DesktopUnavailable(providerID string) bool {
	return providerID == "doubao-work" && runtime.GOOS != "darwin" && runtime.GOOS != "windows"
}
func (m *Manager) Auth(ctx context.Context, s Source, method string, input map[string]any, result any) error {
	if DesktopUnavailable(s.ProviderID) {
		return errors.New("MODEL_PLUGIN_DESKTOP_UNAVAILABLE")
	}
	if DesktopAppMissing(s.ProviderID) {
		return errors.New("MODEL_PLUGIN_DESKTOP_APP_MISSING")
	}
	switch method {
	case "prompt", "validate", "authorize", "callback", "apiKey", "signOut":
	default:
		return errors.New("MODEL_PLUGIN_INVALID_AUTH_METHOD")
	}
	w, err := m.getWorker(ctx, s)
	if err != nil {
		return err
	}
	params := map[string]any{}
	for k, v := range input {
		params[k] = v
	}
	params["provider"] = s.ProviderID
	params["account"] = s.ProviderID
	if err := w.host.Call(ctx, method, params, result); err != nil {
		return err
	}
	if reply, ok := result.(*AuthReply); ok && (reply.OK && (method == "apiKey" || method == "callback") || method == "signOut") && m.AuthChanged != nil {
		return m.AuthChanged(s.ID)
	}
	return nil
}
func (m *Manager) SetOptions(ctx context.Context, s Source, options map[string]any) error {
	s.Options = options
	m.mu.Lock()
	err := m.save(s)
	if err == nil {
		removeErr := os.Remove(filepath.Join(m.Root, "sources", s.ID, "provider.json"))
		if removeErr != nil && !os.IsNotExist(removeErr) {
			err = removeErr
		}
	}
	m.mu.Unlock()
	if err != nil {
		return err
	}
	if m.AuthChanged != nil {
		if err = m.AuthChanged(s.ID); err != nil {
			return err
		}
	}
	_, err = m.getWorker(ctx, s)
	return err
}

func ModelProtocol(model Model, provider Provider) string {
	npm := model.NPM
	if npm == "" {
		npm = provider.NPM
	}
	switch npm {
	case "@ai-sdk/anthropic":
		return "anthropic-messages"
	case "@ai-sdk/openai":
		return "openai-responses"
	default:
		return "openai-completions"
	}
}
func (m *Manager) Fetch(ctx context.Context, s Source, model Model, provider Provider, request *http.Request, body []byte) (*http.Response, error) {
	if DesktopUnavailable(s.ProviderID) {
		return nil, errors.New("MODEL_PLUGIN_DESKTOP_UNAVAILABLE")
	}
	w, err := m.getWorker(ctx, s)
	if err != nil {
		return nil, err
	}
	if provider.MaxConcurrency == 1 {
		select {
		case w.gate <- struct{}{}:
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
	if model.NPM == "" {
		model.NPM = provider.NPM
	}
	headers := map[string]string{}
	for key := range request.Header {
		headers[key] = request.Header.Get(key)
	}
	response, err := w.host.Fetch(ctx, map[string]any{"provider": s.ProviderID, "account": s.ProviderID, "model": model.ID, "npm": model.NPM, "url": request.URL.String(), "method": request.Method, "headers": headers, "body": base64.StdEncoding.EncodeToString(body)})
	if provider.MaxConcurrency == 1 {
		if err != nil {
			<-w.gate
		} else {
			response.Body = &serialBody{ReadCloser: response.Body, release: func() { <-w.gate }}
		}
	}
	return response, err
}
func (m *Manager) remove(s Source) {
	m.mu.Lock()
	w := m.workers[s.ID]
	delete(m.workers, s.ID)
	m.mu.Unlock()
	if w != nil {
		w.close()
	}
	if s.ProviderID == "doubao-work" && !DesktopUnavailable(s.ProviderID) {
		_ = os.Remove(filepath.Join(m.Root, "sources", s.ID, "source.json"))
		_ = os.Remove(filepath.Join(m.Root, "sources", s.ID, "provider.json"))
		return
	}
	_ = os.RemoveAll(filepath.Join(m.Root, "sources", s.ID))
}
func (m *Manager) Close() {
	m.mu.Lock()
	m.closed = true
	for _, job := range m.jobs {
		job.Cancel()
	}
	workers := m.workers
	m.workers = map[string]*worker{}
	m.mu.Unlock()
	for _, w := range workers {
		w.close()
	}
}

type serialBody struct {
	io.ReadCloser
	once    sync.Once
	release func()
}

func (b *serialBody) Close() error { err := b.ReadCloser.Close(); b.once.Do(b.release); return err }

func (m *Manager) persistProvider(s Source, p Provider) error {
	dir := filepath.Join(m.Root, "sources", s.ID)
	data, err := json.Marshal(providerCache{Provider: p, OptionsHash: sourceOptionsFingerprint(s.Options)})
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(dir, ".provider-")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	_, err = f.Write(data)
	if closeErr := f.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	return os.Rename(f.Name(), filepath.Join(dir, "provider.json"))
}
func (m *Manager) CachedProvider(s Source) (Provider, error) {
	if !sourceID.MatchString(s.ID) {
		return Provider{}, ErrInvalidPackage
	}
	data, err := os.ReadFile(filepath.Join(m.Root, "sources", s.ID, "provider.json"))
	if err != nil {
		return Provider{}, err
	}
	var cache providerCache
	if json.Unmarshal(data, &cache) != nil || cache.Provider.ID != s.ProviderID || cache.OptionsHash != sourceOptionsFingerprint(s.Options) {
		return Provider{}, errors.New("MODEL_PLUGIN_MODELS_REQUIRED")
	}
	p := cache.Provider

	return p, nil
}

func (m *Manager) Packages() []Package {
	entries, _ := os.ReadDir(m.PackagesRoot())
	packages := []Package{}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		if pkg, err := m.ReadPackage(entry.Name()); err == nil {
			packages = append(packages, pkg)
		}
	}
	return packages
}

type providerCache struct {
	Provider    Provider `json:"provider"`
	OptionsHash string   `json:"optionsHash"`
}

func sourceOptionsFingerprint(options map[string]any) string {
	raw, _ := json.Marshal(options)
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}
func (m *Manager) synchronizeOptions(ctx context.Context, s Source, w *worker) error {
	if s.ProviderID == "" {
		return nil
	}
	w.configMu.Lock()
	defer w.configMu.Unlock()
	current, err := m.ReadSource(s.ID)
	if err != nil {
		return err
	}
	signature := sourceOptionsFingerprint(current.Options)
	if w.configuration == signature {
		return nil
	}
	if err = w.host.Call(ctx, "setProviderOptions", map[string]any{"options": map[string]any{current.ProviderID: current.Options}}, nil); err != nil {
		return err
	}
	w.configuration = signature
	return nil
}
