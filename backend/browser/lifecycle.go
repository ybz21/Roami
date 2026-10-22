package browser

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/gorilla/websocket"
	"github.com/ybz21/Roami/internal/browsertabs"
)

var restarting atomic.Bool

type restartResult struct {
	OK           bool   `json:"ok"`
	BrowserID    string `json:"browserId"`
	RestoredTabs int    `json:"restoredTabs"`
}

func localCDP() bool {
	u, err := url.Parse(cdpAddress())
	if err != nil || u.Scheme != "http" {
		return false
	}
	host := u.Hostname()
	return host == "localhost" || net.ParseIP(host).IsLoopback()
}

// Match the browser root, never a renderer or an unrelated process group.
func chromePID(ps string, port int) int {
	for _, line := range strings.Split(ps, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 3 {
			continue
		}
		name := filepath.Base(fields[1])
		if name != "chrome" && name != "chromium" && name != "chromium-browser" && name != "google-chrome" && !strings.Contains(line, "/Google Chrome.app/Contents/MacOS/Google Chrome ") {
			continue
		}
		found, child := false, false
		for _, arg := range fields[2:] {
			found = found || arg == "--remote-debugging-port="+strconv.Itoa(port)
			child = child || strings.HasPrefix(arg, "--type=")
		}
		if found && !child {
			pid, _ := strconv.Atoi(fields[0])
			return pid
		}
	}
	return 0
}

func currentChromePID() int {
	if !localCDP() {
		return 0
	}
	out, err := exec.Command("ps", "-eo", "pid=,args=").Output()
	if err != nil {
		return 0
	}
	return chromePID(string(out), cdpPort())
}

func pageURLs(pages []target) []string {
	var urls []string
	for _, page := range pages {
		if page.URL != "" && page.URL != "about:blank" {
			urls = append(urls, page.URL)
		}
	}
	return urls
}

func stopLocalChrome() error {
	pid := currentChromePID()
	if pid == 0 {
		if !portFree(cdpPort()) {
			return fmt.Errorf("cannot identify the local Chrome process on port %d", cdpPort())
		}
		return nil
	}
	// Browser.close flushes profile data even when this server did not launch Chrome.
	if identity, err := currentBrowserIdentity(); err == nil {
		u, _ := url.Parse(cdpAddress())
		u.Scheme, u.Path = "ws", "/devtools/browser/"+identity
		dialer := websocket.Dialer{HandshakeTimeout: time.Second}
		if conn, _, err := dialer.Dial(u.String(), nil); err == nil {
			_ = conn.SetWriteDeadline(time.Now().Add(time.Second))
			_ = conn.WriteJSON(map[string]any{"id": 1, "method": "Browser.close"})
			_ = conn.Close()
		}
	}
	for attempt := 0; attempt < 2; attempt++ {
		for deadline := time.Now().Add(2 * time.Second); time.Now().Before(deadline); {
			if currentChromePID() != pid {
				return nil
			}
			time.Sleep(100 * time.Millisecond)
		}
		if currentChromePID() != pid {
			return nil
		}
		signal := syscall.SIGTERM
		if attempt == 1 {
			signal = syscall.SIGKILL
		}
		if err := syscall.Kill(pid, signal); err != nil && err != syscall.ESRCH {
			return err
		}
	}
	for deadline := time.Now().Add(2 * time.Second); time.Now().Before(deadline); {
		if currentChromePID() != pid {
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	return fmt.Errorf("Chrome did not exit")
}

func restartChrome(fallback []string) (restartResult, error) {
	if !restarting.CompareAndSwap(false, true) {
		return restartResult{}, fmt.Errorf("Chrome restart already in progress")
	}
	defer restarting.Store(false)
	launchMu.Lock()
	defer launchMu.Unlock()
	if !localCDP() {
		return restartResult{}, fmt.Errorf("remote Chrome must be restarted on its host")
	}
	old, _ := currentBrowserIdentity()
	pages := listPages()
	urls := pageURLs(pages)
	if len(pages) == 0 {
		urls = fallback
		if urls == nil {
			urls = savedRecoveryURLs()
		}
	}
	rememberRecoveryURLs(urls)
	origins := savedRecoveryTabs()
	if err := stopLocalChrome(); err != nil {
		setLastErr(err.Error())
		return restartResult{}, err
	}
	// Wait may not yet have cleared the adopted exec.Cmd.
	procMu.Lock()
	chrome = nil
	procMu.Unlock()
	lastLaunch = time.Time{}
	if err := ensureChromeLocked(); err != nil {
		return restartResult{}, err
	}
	identity, err := currentBrowserIdentity()
	if err != nil || identity == old {
		return restartResult{}, fmt.Errorf("Chrome did not start a new browser instance")
	}
	restored, err := restoreTabs(urls, origins)
	if err != nil {
		setLastErr(err.Error())
		return restartResult{}, err
	}
	setLastErr("")
	return restartResult{OK: true, BrowserID: identity, RestoredTabs: restored}, nil
}

func restoreTabs(urls []string, origins []recoveryTab) (int, error) {
	var identity, first string
	if len(origins) > 0 {
		urls = make([]string, len(origins))
		for i, tab := range origins {
			urls[i] = tab.URL
		}
		var err error
		identity, err = currentBrowserIdentity()
		if err != nil {
			return 0, err
		}
	}
	available := map[string]int{}
	for _, page := range listPages() {
		available[page.URL]++
	}
	for i, address := range urls {
		if len(origins) == 0 && available[address] > 0 {
			available[address]--
			continue
		}
		id, err := newTab(address)
		if err != nil {
			return 0, fmt.Errorf("Chrome restarted but could not restore a tab: %w", err)
		}
		if first == "" {
			first = id
		}
		if i < len(origins) {
			tab := origins[i]
			if tab.CreatedBy == "" {
				tab.CreatedBy = "agent"
			}
			if _, err = tabCatalog(browsertabs.Event{Action: "restore", BrowserID: identity, TargetID: id, Origin: tab.Origin, Pinned: &tab.Pinned, CreatedBy: tab.CreatedBy}); err != nil {
				return 0, err
			}
		}
	}
	if len(urls) > 0 {
		for _, page := range listPages() {
			if page.URL == "about:blank" {
				_ = closeTab(page.ID)
			}
		}
		if first != "" {
			_ = activateTab(first)
			return len(urls), nil
		}
		for _, page := range listPages() {
			if page.URL == urls[0] {
				_ = activateTab(page.ID)
				break
			}
		}
	}
	return len(urls), nil
}

type recoveryTab struct {
	CreatedBy string `json:"createdBy"`
	URL       string `json:"url"`
	Origin    string `json:"origin"`
	Pinned    bool   `json:"pinned"`
}
type recoverySnapshot struct {
	Tabs    []recoveryTab `json:"tabs,omitempty"`
	Profile string        `json:"profile"`
	URLs    []string      `json:"urls"`
}

func recoveryFile() string {
	cfgStore.mu.Lock()
	defer cfgStore.mu.Unlock()
	if cfgStore.file == "" {
		return ""
	}
	return filepath.Join(filepath.Dir(cfgStore.file), "browser-recovery.json")
}

func savedRecoveryURLs() []string {
	var snapshot recoverySnapshot
	b, _ := os.ReadFile(recoveryFile())
	if json.Unmarshal(b, &snapshot) != nil || snapshot.Profile != effectiveConfig().Profile {
		return nil
	}
	return snapshot.URLs
}

func rememberRecoveryURLs(urls []string) {
	file := recoveryFile()
	if file == "" {
		return
	}
	tabs := savedRecoveryTabs()
	if identity, err := currentBrowserIdentity(); err == nil {
		pages := listPages()
		ids := make([]string, 0, len(pages))
		for _, p := range pages {
			ids = append(ids, p.ID)
		}
		if catalog, err := tabCatalog(browsertabs.Event{Action: "sync", BrowserID: identity, Targets: ids}); err == nil {
			tabs = nil
			for _, p := range pages {
				if p.URL != "" && p.URL != "about:blank" {
					meta := catalog.Entries[p.ID]
					tabs = append(tabs, recoveryTab{URL: p.URL, Origin: meta.Origin, Pinned: meta.Pinned, CreatedBy: meta.CreatedBy})
				}
			}
		}
	}
	data, _ := json.Marshal(recoverySnapshot{Profile: effectiveConfig().Profile, URLs: urls, Tabs: tabs})
	cfgStore.mu.Lock()
	defer cfgStore.mu.Unlock()
	if err := os.WriteFile(file+".tmp", data, 0o600); err == nil {
		_ = os.Rename(file+".tmp", file)
	}
}

func pageResponds(ctx context.Context, page target) bool {
	dialer := websocket.Dialer{HandshakeTimeout: time.Second}
	conn, _, err := dialer.DialContext(ctx, page.WebSocketDebuggerURL, nil)
	if err != nil {
		return false
	}
	defer conn.Close()
	deadline := time.Now().Add(2 * time.Second)
	if end, ok := ctx.Deadline(); ok && end.Before(deadline) {
		deadline = end
	}
	_ = conn.SetWriteDeadline(deadline)
	_ = conn.SetReadDeadline(deadline)
	if conn.WriteJSON(map[string]any{"id": 1, "method": "Runtime.evaluate", "params": map[string]any{"expression": "document.readyState", "returnByValue": true}}) != nil {
		return false
	}
	for {
		var reply struct {
			ID    int             `json:"id"`
			Error json.RawMessage `json:"error"`
		}
		if conn.ReadJSON(&reply) != nil {
			return false
		}
		if reply.ID == 1 {
			return len(reply.Error) == 0
		}
	}
}

func anyPageResponds(ctx context.Context, pages []target) bool {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	jobs := make(chan target)
	var healthy atomic.Bool
	var workers sync.WaitGroup
	for i := 0; i < min(4, len(pages)); i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for page := range jobs {
				if ctx.Err() == nil && !healthy.Load() && pageResponds(ctx, page) {
					healthy.Store(true)
					cancel()
				}
			}
		}()
	}
	for _, page := range pages {
		select {
		case jobs <- page:
		case <-ctx.Done():
		}
	}
	close(jobs)
	workers.Wait()
	return healthy.Load()
}

// StartRecovery monitors only the local browser once used, including CLI-owned instances.
func StartRecovery(parent context.Context) func() {
	ctx, cancel := context.WithCancel(parent)
	done := make(chan struct{})
	go func() {
		defer close(done)
		ticker := time.NewTicker(5 * time.Second)
		defer ticker.Stop()
		urls := savedRecoveryURLs()
		watched, failures := len(urls) > 0, 0
		var lastAttempt time.Time
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
			}
			if !localCDP() || restarting.Load() {
				failures = 0
				continue
			}
			if !launchMu.TryLock() {
				continue
			}
			if restarting.Load() {
				launchMu.Unlock()
				continue
			}
			pid := currentChromePID()
			up := alive()
			watched = watched || pid > 0 || up
			if !watched {
				launchMu.Unlock()
				continue
			}
			pages := listPages()
			if up {
				next := pageURLs(pages)
				if !slices.Equal(urls, next) {
					urls = next
					rememberRecoveryURLs(urls)
				}
				if !*effectiveConfig().AutoRecover {
					failures = 0
					launchMu.Unlock()
					continue
				}
				if len(pages) == 0 || anyPageResponds(ctx, pages) {
					failures = 0
					launchMu.Unlock()
					continue
				}
			}
			launchMu.Unlock()
			if !*effectiveConfig().AutoRecover {
				failures = 0
				continue
			}
			failures++
			if ctx.Err() != nil {
				return
			}
			if failures < 2 || time.Since(lastAttempt) < time.Minute {
				continue
			}
			lastAttempt, failures = time.Now(), 0
			if _, err := restartChrome(urls); err != nil {
				setLastErr(err.Error())
			}
		}
	}()
	return func() { cancel(); <-done }
}

func savedRecoveryTabs() []recoveryTab {
	var snapshot recoverySnapshot
	b, _ := os.ReadFile(recoveryFile())
	if json.Unmarshal(b, &snapshot) != nil || snapshot.Profile != effectiveConfig().Profile {
		return nil
	}
	return snapshot.Tabs
}
