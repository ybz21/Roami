package browser

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/ybz21/Roami/internal/browsertabs"
)

type recoverySink struct {
	done   chan struct{}
	errors chan string
	frames chan []byte
	once   sync.Once
}

func (s *recoverySink) writeBinary(frame []byte) error {
	select {
	case s.frames <- frame:
	default:
	}
	return nil
}
func (s *recoverySink) writeText(value any) error {
	data, _ := json.Marshal(value)
	var message struct {
		Type string `json:"type"`
		Msg  string `json:"msg"`
	}
	_ = json.Unmarshal(data, &message)
	if message.Type == "error" {
		s.errors <- message.Msg
	}
	return nil
}
func (s *recoverySink) onCtrl(func([]byte))          {}
func (s *recoverySink) close()                       { s.once.Do(func() { close(s.done) }) }
func (s *recoverySink) wait()                        { <-s.done }
func (s *recoverySink) awaitSlot() (uint16, bool)    { return 1, !s.closed() }
func (s *recoverySink) onAck(uint16) (float64, bool) { return 0, true }
func (s *recoverySink) closed() bool {
	select {
	case <-s.done:
		return true
	default:
		return false
	}
}

func TestScreencastRejectsAnUnresponsiveRenderer(t *testing.T) {
	for _, initiallyResponsive := range []bool{false, true} {
		t.Run(fmt.Sprint(initiallyResponsive), func(t *testing.T) {
			var endpoint string
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				switch r.URL.Path {
				case "/json/version":
					fmt.Fprint(w, `{"User-Agent":"fixture"}`)
				case "/json":
					fmt.Fprintf(w, `[{"id":"tab","type":"page","url":"about:blank","webSocketDebuggerUrl":%q}]`, endpoint)
				case "/devtools/page/tab":
					conn, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
					if err != nil {
						return
					}
					defer conn.Close()
					probes := 0
					for {
						var command struct {
							ID     int    `json:"id"`
							Method string `json:"method"`
						}
						if conn.ReadJSON(&command) != nil {
							return
						}
						if command.Method == "Runtime.evaluate" {
							probes++
							if !initiallyResponsive {
								continue
							}
							if probes > 1 {
								continue
							}
						}
						_ = conn.WriteJSON(map[string]any{"id": command.ID, "result": map[string]any{}})
						if command.Method == "Page.startScreencast" {
							_ = conn.WriteJSON(map[string]any{"method": "Page.screencastFrame", "params": map[string]any{
								"data": base64.StdEncoding.EncodeToString([]byte("image")), "sessionId": 1,
								"metadata": map[string]any{"deviceWidth": 1280, "deviceHeight": 800},
							}})
						}
					}
				}
			}))
			defer server.Close()
			endpoint = strings.Replace(server.URL, "http://", "ws://", 1) + "/devtools/page/tab"
			previous, interval, timeout := CDPBase, rendererProbeInterval, rendererProbeTimeout
			CDPBase, rendererProbeInterval, rendererProbeTimeout = server.URL, 20*time.Millisecond, 60*time.Millisecond
			defer func() { CDPBase, rendererProbeInterval, rendererProbeTimeout = previous, interval, timeout }()
			sink := &recoverySink{done: make(chan struct{}), errors: make(chan string, 1), frames: make(chan []byte, 1)}
			finished := make(chan struct{})
			go func() { runScreencast(sink, scOptions{target: "tab"}); close(finished) }()
			if initiallyResponsive {
				select {
				case <-sink.frames:
				case <-time.After(time.Second):
					t.Fatal("responsive page did not produce its first frame")
				}
			}
			select {
			case code := <-sink.errors:
				if code != "BROWSER_PAGE_UNRESPONSIVE" {
					t.Fatalf("unexpected error: %s", code)
				}
			case <-time.After(time.Second):
				sink.close()
				t.Fatal("renderer stalled while the transport stayed healthy")
			}
			sink.close()
			<-finished
		})
	}
}

func TestNewTabPreservesTheEntireURL(t *testing.T) {
	address := "https://example.test/?a=1&b=2#/projects?tab=one"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		value, err := url.QueryUnescape(r.URL.RawQuery)
		if err != nil || value != address || r.Method != http.MethodPut {
			t.Errorf("navigation URL changed: %q %v", value, err)
		}
		fmt.Fprint(w, `{"id":"created"}`)
	}))
	defer server.Close()
	previous := CDPBase
	CDPBase = server.URL
	defer func() { CDPBase = previous }()
	if id, err := newTab(address); err != nil || id != "created" {
		t.Fatalf("new tab: %q %v", id, err)
	}
}

func TestScreencastKeepsPendingNavigationAvailable(t *testing.T) {
	for _, scenario := range []string{"settles", "times-out", "subframe"} {
		t.Run(scenario, func(t *testing.T) {
			var endpoint string
			var writeMu sync.Mutex
			var responsive atomic.Bool
			connections := make(chan *websocket.Conn, 1)
			write := func(conn *websocket.Conn, value any) {
				writeMu.Lock()
				defer writeMu.Unlock()
				_ = conn.WriteJSON(value)
			}
			frame := map[string]any{"method": "Page.screencastFrame", "params": map[string]any{
				"data": base64.StdEncoding.EncodeToString([]byte("image")), "sessionId": 1,
				"metadata": map[string]any{"deviceWidth": 1280, "deviceHeight": 800},
			}}
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				switch r.URL.Path {
				case "/json/version":
					fmt.Fprint(w, `{"User-Agent":"fixture"}`)
				case "/json":
					fmt.Fprintf(w, `[{"id":"tab","type":"page","url":"about:blank","webSocketDebuggerUrl":%q}]`, endpoint)
				case "/devtools/page/tab":
					conn, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
					if err != nil {
						return
					}
					defer conn.Close()
					connections <- conn
					for {
						var command struct {
							ID     int    `json:"id"`
							Method string `json:"method"`
						}
						if conn.ReadJSON(&command) != nil {
							return
						}
						if command.Method == "Page.enable" {
							id := "tab"
							if scenario == "subframe" {
								id = "child"
							}
							write(conn, map[string]any{"method": "Page.frameStartedNavigating", "params": map[string]any{"frameId": id}})
						}
						if !responsive.Load() && (command.Method == "Runtime.evaluate" || command.Method == "Page.enable") {
							continue
						}
						write(conn, map[string]any{"id": command.ID, "result": map[string]any{}})
						if command.Method == "Page.startScreencast" {
							write(conn, frame)
						}
					}
				}
			}))
			defer server.Close()
			endpoint = strings.Replace(server.URL, "http://", "ws://", 1) + "/devtools/page/tab"
			previous, interval, timeout, navigationTimeout := CDPBase, rendererProbeInterval, rendererProbeTimeout, rendererNavigationTimeout
			CDPBase, rendererProbeInterval, rendererProbeTimeout, rendererNavigationTimeout = server.URL, 10*time.Millisecond, 40*time.Millisecond, 200*time.Millisecond
			defer func() {
				CDPBase, rendererProbeInterval, rendererProbeTimeout, rendererNavigationTimeout = previous, interval, timeout, navigationTimeout
			}()
			sink := &recoverySink{done: make(chan struct{}), errors: make(chan string, 4), frames: make(chan []byte, 1)}
			finished := make(chan struct{})
			go func() { runScreencast(sink, scOptions{target: "tab"}); close(finished) }()
			defer func() { sink.close(); <-finished }()
			var conn *websocket.Conn
			select {
			case conn = <-connections:
			case <-time.After(time.Second):
				t.Fatal("stream did not connect")
			}
			select {
			case <-sink.frames:
			case <-time.After(time.Second):
				t.Fatal("navigation must not block the first frame")
			}
			if scenario == "subframe" {
				select {
				case code := <-sink.errors:
					if code != "BROWSER_PAGE_UNRESPONSIVE" {
						t.Fatalf("subframe hid a stalled main frame: %s", code)
					}
				case <-time.After(time.Second):
					t.Fatal("stalled main frame was not detected")
				}
				return
			}
			select {
			case code := <-sink.errors:
				t.Fatalf("navigation was mistaken for a stalled renderer: %s", code)
			case <-time.After(80 * time.Millisecond):
			}
			if scenario == "times-out" {
				select {
				case code := <-sink.errors:
					if code != "BROWSER_NAVIGATION_TIMEOUT" {
						t.Fatalf("unexpected error: %s", code)
					}
				case <-time.After(time.Second):
					t.Fatal("navigation did not time out")
				}
				if sink.closed() {
					t.Fatal("navigation timeout disconnected the recovery controls")
				}
			}
			responsive.Store(true)
			write(conn, map[string]any{"method": "Page.frameStoppedLoading", "params": map[string]any{"frameId": "tab"}})
			write(conn, frame)
			select {
			case <-sink.frames:
			case <-time.After(time.Second):
				t.Fatal("settled navigation did not resume frames")
			}
			select {
			case code := <-sink.errors:
				t.Fatalf("old context probe survived navigation: %s", code)
			case <-time.After(80 * time.Millisecond):
			}
		})
	}
}

func TestNewTabReturnsTargetWithoutWaitingForNavigation(t *testing.T) {
	const address = "https://slow.example/?a=1&b=2"
	InitConfig(t.TempDir())
	defer func() { cfgStore.mu.Lock(); cfgStore.file, cfgStore.portFile = "", ""; cfgStore.mu.Unlock() }()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/json/version":
			fmt.Fprint(w, `{"webSocketDebuggerUrl":"ws://fixture/devtools/browser/original"}`)
		case "/json":
			fmt.Fprint(w, `[]`)
		case "/json/new":
			value, err := url.QueryUnescape(r.URL.RawQuery)
			if err != nil || value != address || r.Method != http.MethodPut {
				t.Errorf("URL changed: %q %v", value, err)
			}
			fmt.Fprint(w, `{"id":"created"}`)
		case "/json/activate/created":
			fmt.Fprint(w, `Target activated`)
		default:
			t.Errorf("new-tab navigation must not attach to the pending renderer: %s", r.URL.Path)
			http.Error(w, "unexpected CDP request", http.StatusBadRequest)
		}
	}))
	defer server.Close()
	previous := CDPBase
	CDPBase = server.URL
	defer func() { CDPBase = previous }()
	router := gin.New()
	router.POST("/tabs", NewTab)
	recorder := httptest.NewRecorder()
	body, _ := json.Marshal(map[string]string{"url": address, "origin": "human"})
	request := httptest.NewRequest(http.MethodPost, "/tabs", strings.NewReader(string(body)))
	request.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK || !strings.Contains(recorder.Body.String(), `"id":"created"`) {
		t.Fatalf("target lost while navigation was pending: %d %s", recorder.Code, recorder.Body.String())
	}
	identity, err := tabCatalog(browsertabs.Event{Action: "sync", BrowserID: "original", Targets: []string{"created"}})
	if err != nil || identity.Entries["created"].Origin != "human" {
		t.Fatalf("new target metadata lost: %+v %v", identity, err)
	}
}
