package modelgateway

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/ybz21/Roami/internal/modelplugins"
)

func TestPluginAccountCapabilitiesUseTheInstalledHook(t *testing.T) {
	if os.Getenv("ROAMI_MAGPIE_BUN") == "" {
		t.Skip("set ROAMI_MAGPIE_BUN for the sandbox integration")
	}
	h := pluginTestHandler(t)
	script := `let checked = false;
export const TestPlugin = async () => ({
  config: async (cfg) => { cfg.provider ??= {}; cfg.provider.benefits = { name: 'Benefits fixture', models: { demo: { name: 'Demo' } } }; },
  auth: { provider: 'benefits', methods: [{ type: 'api', label: 'Key' }],
    usage: async () => ({ balance: checked ? '35 credits' : '30 credits' }),
    refresh: async (auth) => auth,
	    calls: async (getAuth, _provider, { since }) => ({
	      calls: (await getAuth())?.key ? [
	        { rid: 'private-receipt', t: since + 20, model: 'fixture-model', in: 40, out: 10, cost: 0, session: 'private-session' },
	        { rid: 'private-receipt', t: since + 10, model: 'duplicate' },
	        { rid: 'old-receipt', t: since - 1, model: 'old-entry' },
	      ] : []
	    }),
    checkin: async (getAuth) => {
      if (!(await getAuth())?.key) throw Error('account missing');
      if (checked) return { outcome: 'done' };
      checked = true;
      return { outcome: 'claimed', credit: 5, streak: 2, message: 'only public result fields' };
    }
  }
});`
	uploaded := pluginUpload(t, h, map[string]string{"package.json": `{"name":"test-benefits","main":"index.mjs"}`, "index.mjs": script}, true)
	var imported struct {
		Data modelplugins.Package `json:"data"`
	}
	if uploaded.Code != http.StatusOK || json.Unmarshal(uploaded.Body.Bytes(), &imported) != nil {
		t.Fatal(uploaded.Body)
	}
	if inspected := pluginJSON(t, h, "POST", "/inspect", map[string]any{"packageId": imported.Data.ID}); !bytes.Contains(inspected, []byte(`"calls":true`)) ||
		!bytes.Contains(inspected, []byte(`"renews":true`)) || !bytes.Contains(inspected, []byte(`"signedIn":false`)) {
		t.Fatalf("capabilities missing before authorization: %s", inspected)
	}
	created := pluginJSON(t, h, "POST", "/sources", map[string]any{"packageId": imported.Data.ID, "providerId": "benefits", "revision": h.Catalog.value.Revision})
	var source struct {
		SourceID string `json:"sourceId"`
	}
	if err := json.Unmarshal(created, &source); err != nil || source.SourceID == "" {
		t.Fatalf("create: %s (%v)", created, err)
	}
	path := "/sources/" + source.SourceID
	read := func(method, action string) *httptest.ResponseRecorder {
		t.Helper()
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest(method, "/v1/model-gateway/plugins"+path+action, nil))
		return w
	}
	if w := read(http.MethodPost, "/check-in"); w.Code != http.StatusConflict {
		t.Fatalf("unsigned check-in: %d %s", w.Code, w.Body)
	}
	if w := read(http.MethodGet, "/calls"); w.Code != http.StatusConflict {
		t.Fatalf("unsigned calls read: %d %s", w.Code, w.Body)
	}
	pluginJSON(t, h, "POST", path+"/auth", map[string]any{"action": "apiKey", "method": 0, "key": "fixture-key"})
	if info := pluginJSON(t, h, "GET", path+"/info", nil); !bytes.Contains(info, []byte(`"checkin":true`)) || !bytes.Contains(info, []byte(`"usage":true`)) {
		t.Fatalf("missing declared capabilities: %s", info)
	}
	if w := read(http.MethodGet, "/check-in"); w.Code != http.StatusMethodNotAllowed {
		t.Fatalf("GET must not invoke check-in: %d", w.Code)
	}
	if calls := pluginJSON(t, h, "GET", path+"/calls", nil); !bytes.Contains(calls, []byte(`"model":"fixture-model"`)) ||
		!bytes.Contains(calls, []byte(`"cost":0`)) || bytes.Contains(calls, []byte("private-")) ||
		bytes.Contains(calls, []byte("duplicate")) || bytes.Contains(calls, []byte("old-entry")) {
		t.Fatalf("unexpected call history: %s", calls)
	}
	if before := pluginJSON(t, h, "GET", path+"/usage", nil); !bytes.Contains(before, []byte(`"balance":"30 credits"`)) {
		t.Fatalf("unexpected initial allowance: %s", before)
	}
	if checked := pluginJSON(t, h, "POST", path+"/check-in", nil); !bytes.Contains(checked, []byte(`"outcome":"claimed"`)) || !bytes.Contains(checked, []byte(`"credit":5`)) || bytes.Contains(checked, []byte(`only public result fields`)) {
		t.Fatalf("unexpected check-in result: %s", checked)
	}
	if after := pluginJSON(t, h, "GET", path+"/usage", nil); !bytes.Contains(after, []byte(`"balance":"35 credits"`)) {
		t.Fatalf("allowance did not update: %s", after)
	}
}
