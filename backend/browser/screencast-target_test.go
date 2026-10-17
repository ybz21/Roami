package browser

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestTaskScreencastPinsBrowserAndTargetWithoutFallback(t *testing.T) {
	for _, mode := range []string{"matching", "replaced", "missing", "changes-during-resolution", "invalid-identity"} {
		t.Run(mode, func(t *testing.T) {
			versions, lists := 0, 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				switch r.URL.Path {
				case "/json/version":
					versions++
					identity := "original"
					if mode == "replaced" || mode == "changes-during-resolution" && versions > 1 {
						identity = "replacement"
					}
					if mode == "invalid-identity" {
						fmt.Fprint(w, `{"webSocketDebuggerUrl":"ws://chrome/devtools/page/original"}`)
						return
					}
					fmt.Fprintf(w, `{"webSocketDebuggerUrl":"ws://chrome/devtools/browser/%s"}`, identity)
				case "/json":
					lists++
					if mode == "missing" {
						fmt.Fprint(w, `[{"id":"unrelated","type":"page","url":"https://example.invalid","webSocketDebuggerUrl":"ws://chrome/unrelated"}]`)
						return
					}
					fmt.Fprint(w, `[{"id":"selected","type":"page","url":"https://example.invalid","webSocketDebuggerUrl":"ws://chrome/selected"}]`)
				default:
					t.Errorf("Scoped takeover must not create a tab or launch a fallback: %s", r.URL.Path)
					w.WriteHeader(http.StatusNotFound)
				}
			}))
			defer server.Close()
			previous := CDPBase
			CDPBase = server.URL
			defer func() { CDPBase = previous }()
			endpoint, err := targetForScreencast(scOptions{target: "selected", expectedBrowser: "original"})
			if mode == "matching" {
				if err != nil || endpoint != "ws://chrome/selected" {
					t.Fatalf("Expected selected target: %q %v", endpoint, err)
				}
			} else if err == nil || endpoint != "" {
				t.Fatalf("Unexpected fallback: %q %v", endpoint, err)
			}
			if (mode == "replaced" || mode == "invalid-identity") && lists != 0 {
				t.Fatal("Browser mismatch queried unrelated target list")
			}
		})
	}
}

func TestTaskScreencastDataChannelKeepsInstanceConstraint(t *testing.T) {
	options := parseDCOptions("screencast#1?target=selected&control=1&expectedBrowser=original")
	if options.target != "selected" || options.expectedBrowser != "original" || !options.control {
		t.Fatalf("Lost scoped takeover: %#v", options)
	}
}
