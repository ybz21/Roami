package browser

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
)

func currentBrowserIdentity() (string, error) {
	response, err := cdpHTTP.Get(CDPBase + "/json/version")
	if err != nil {
		return "", fmt.Errorf("BROWSER_RESOURCE_CHANGED")
	}
	defer response.Body.Close()
	var version struct {
		WebSocket string `json:"webSocketDebuggerUrl"`
	}
	if response.StatusCode != http.StatusOK || json.NewDecoder(io.LimitReader(response.Body, 64<<10)).Decode(&version) != nil {
		return "", fmt.Errorf("BROWSER_RESOURCE_CHANGED")
	}
	endpoint, err := url.Parse(version.WebSocket)
	if err != nil || (endpoint.Scheme != "ws" && endpoint.Scheme != "wss") {
		return "", fmt.Errorf("BROWSER_RESOURCE_CHANGED")
	}
	parts := strings.Split(endpoint.Path, "/")
	if len(parts) != 4 || parts[1] != "devtools" || parts[2] != "browser" || len(parts[3]) == 0 || len(parts[3]) > 128 {
		return "", fmt.Errorf("BROWSER_RESOURCE_CHANGED")
	}
	for _, r := range parts[3] {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '_') {
			return "", fmt.Errorf("BROWSER_RESOURCE_CHANGED")
		}
	}
	return parts[3], nil
}

func ensureBrowserInstance(expected string) error {
	if expected == "" {
		return ensureChrome()
	}
	identity, err := currentBrowserIdentity()
	if err != nil || identity != expected {
		return fmt.Errorf("BROWSER_RESOURCE_CHANGED")
	}
	return nil
}

func targetForScreencast(options scOptions) (string, error) {
	if options.expectedBrowser == "" {
		if err := ensureBrowserInstance(""); err != nil {
			return "", err
		}
		return targetWS(options.target)
	}
	if options.target == "" {
		return "", fmt.Errorf("BROWSER_TARGET_UNAVAILABLE")
	}
	identity, err := currentBrowserIdentity()
	if err != nil || identity != options.expectedBrowser {
		return "", fmt.Errorf("BROWSER_RESOURCE_CHANGED")
	}
	endpoint, err := targetWS(options.target)
	if err != nil {
		return "", fmt.Errorf("BROWSER_TARGET_UNAVAILABLE")
	}
	identity, err = currentBrowserIdentity()
	if err != nil || identity != options.expectedBrowser {
		return "", fmt.Errorf("BROWSER_RESOURCE_CHANGED")
	}
	return endpoint, nil
}
