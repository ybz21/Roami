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
	"testing"
	"time"

	"github.com/gorilla/websocket"
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
								return
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
