package modelgateway

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/json"
	"io"
	"mime/multipart"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/modelplugins"
)

func pluginTestHandler(t *testing.T) *Handler {
	t.Helper()
	originalPath := os.Getenv("PATH")
	h := catalogHandler(t, "https://existing.example/v1", "openai-completions")
	t.Setenv("PATH", os.Getenv("PATH")+string(os.PathListSeparator)+originalPath)
	manager, err := modelplugins.NewManager(filepath.Join(t.TempDir(), "plugins"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(manager.Close)
	manager.AuthChanged = h.pluginAuthChanged
	h.Plugins = manager
	h.Catalog.plugins = manager
	return h
}
func pluginJSON(t *testing.T, h *Handler, method, path string, input any) json.RawMessage {
	t.Helper()
	body, _ := json.Marshal(input)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest(method, "/v1/model-gateway/plugins"+path, bytes.NewReader(body)))
	if w.Code != 200 && w.Code != 202 {
		t.Fatalf("%s %s: %d %s", method, path, w.Code, w.Body)
	}
	var response struct {
		Data json.RawMessage `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	return response.Data
}
func pluginUpload(t *testing.T, h *Handler, files map[string]string, zipped bool) *httptest.ResponseRecorder {
	t.Helper()
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	if zipped {
		var archive bytes.Buffer
		z := zip.NewWriter(&archive)
		for name, data := range files {
			f, _ := z.Create("provider/" + name)
			_, _ = io.WriteString(f, data)
		}
		_ = z.Close()
		part, _ := writer.CreateFormFile("files", "provider.zip")
		_, _ = part.Write(archive.Bytes())
	} else {
		for name, data := range files {
			part, _ := writer.CreateFormFile("files", filepath.Base(name))
			_, _ = io.WriteString(part, data)
			_ = writer.WriteField("paths", "provider/"+name)
		}
	}
	_ = writer.Close()
	request := httptest.NewRequest("POST", "/v1/model-gateway/plugins/import", &body)
	request.Header.Set("Content-Type", writer.FormDataContentType())
	w := httptest.NewRecorder()
	h.ServeHTTP(w, request)
	return w
}
func TestPluginFolderAndZIPImportEndpoints(t *testing.T) {
	h := pluginTestHandler(t)
	files := map[string]string{"package.json": `{"name":"test-plugin","main":"index.mjs"}`, "index.mjs": "export const Plugin=async()=>({})"}
	folder := pluginUpload(t, h, files, false)
	zipped := pluginUpload(t, h, files, true)
	if folder.Code != 200 || zipped.Code != 200 {
		t.Fatalf("import failed: %d %d", folder.Code, zipped.Code)
	}
	if folder.Body.String() != zipped.Body.String() {
		t.Fatal("folder and ZIP created different packages")
	}
	bad := pluginUpload(t, h, map[string]string{"../outside": "bad"}, false)
	if bad.Code != 400 {
		t.Fatal("unsafe upload accepted")
	}
	if w := requestWithKey(h, h.Catalog.credential("opencode"), "/v1/model-gateway/plugins/packages", ""); w.Code != 404 {
		t.Fatal("public gateway exposed plugin management")
	}
}
func TestPluginSourceUsesNativeProtocolAndPrivateCredential(t *testing.T) {
	if os.Getenv("ROAMI_MAGPIE_BUN") == "" {
		t.Skip("set ROAMI_MAGPIE_BUN for the sandbox integration")
	}
	h := pluginTestHandler(t)
	script := `export const Plugin=async()=>({config:async cfg=>{cfg.provider??={};cfg.provider.probe={name:'Probe',npm:'@ai-sdk/anthropic',api:'https://probe.invalid/v1',models:{native:{name:'Native',id:'vendor-native',provider:{api:'https://probe.invalid/v1',npm:'@ai-sdk/anthropic'},limit:{context:1000,output:100}}}}},auth:{provider:'probe',methods:[{type:'api',label:'Key'}],loader:async getAuth=>({apiKey:(await getAuth())?.key,fetch:async(url,init)=>{const headers=new Headers(init.headers);const body=JSON.parse(init.body);const verified={key:headers.get('x-api-key')==='fixture-vendor-private',client:!headers.get('authorization')?.includes('fixture-client-private'),model:body.model==='vendor-native',url:url.endsWith('/messages')};if(Object.values(verified).some(v=>!v))throw Error(JSON.stringify(verified));return new Response(JSON.stringify({id:'message-test',type:'message',role:'assistant',model:'vendor-native',content:[{type:'text',text:'plugin passed'}],stop_reason:'end_turn',usage:{input_tokens:2,output_tokens:3}}),{headers:{'content-type':'application/json'}})}})}})`
	upload := pluginUpload(t, h, map[string]string{"package.json": `{"name":"test-native-provider","main":"index.mjs"}`, "index.mjs": script}, true)
	if upload.Code != 200 {
		t.Fatal(upload.Body)
	}
	var imported struct {
		Data modelplugins.Package `json:"data"`
	}
	_ = json.Unmarshal(upload.Body.Bytes(), &imported)
	providers := pluginJSON(t, h, "POST", "/inspect", map[string]any{"packageId": imported.Data.ID})
	if !bytes.Contains(providers, []byte(`"probe"`)) {
		t.Fatal("provider not listed")
	}
	created := pluginJSON(t, h, "POST", "/sources", map[string]any{"packageId": imported.Data.ID, "providerId": "probe", "revision": h.Catalog.value.Revision})
	var source struct {
		SourceID string `json:"sourceId"`
	}
	_ = json.Unmarshal(created, &source)
	pluginJSON(t, h, "POST", "/sources/"+source.SourceID+"/auth", map[string]any{"action": "apiKey", "method": 0, "key": "fixture-vendor-private"})
	next := h.Catalog.snapshot()
	next.Models = append(next.Models, CatalogModel{ID: "plugin-route", Name: "Plugin", Protocol: "openai-completions", Strategy: "fixed", Candidates: []ModelCandidate{{SourceID: source.SourceID, Model: "native"}}})
	if err := h.Catalog.update(context.Background(), next); err != nil {
		t.Fatal(err)
	}
	if w := setAccessKey(t, h, "PUT", "fixture-client-private", h.Catalog.value.Revision); w.Code != 200 {
		t.Fatal(w.Body)
	}
	response := requestWithKey(h, "fixture-client-private", "/v1/chat/completions", `{"model":"plugin-route","messages":[{"role":"user","content":"test"}],"max_tokens":20}`)
	if response.Code != 200 || !strings.Contains(response.Body.String(), "plugin passed") {
		t.Fatalf("inference: %d %s", response.Code, response.Body)
	}
	stats, err := h.Ledger.StatisticsForSource(1, "", "", "external")
	if err != nil || len(stats.Recent) != 1 || stats.Recent[0].SourceID != source.SourceID {
		t.Fatalf("plugin usage not attributed: %+v %v", stats, err)
	}

	saved, err := h.Plugins.ReadSource(source.SourceID)
	if err != nil {
		t.Fatal(err)
	}
	if err = h.Plugins.SetOptions(context.Background(), saved, map[string]any{"example": true}); err != nil {
		t.Fatal(err)
	}
	if _, err = h.Plugins.CachedProvider(saved); err == nil {
		t.Fatal("parameter change retained stale model routes")
	}
	blocked := requestWithKey(h, "fixture-client-private", "/v1/chat/completions", `{"model":"plugin-route","messages":[{"role":"user","content":"test"}]}`)
	if blocked.Code != 503 || !strings.Contains(blocked.Body.String(), "MODEL_PLUGIN_MODELS_REQUIRED") {
		t.Fatalf("stale route not blocked: %d %s", blocked.Code, blocked.Body)
	}
	if _, err = h.Plugins.Provider(context.Background(), saved); err == nil {
		t.Fatal("stale parameter snapshot repopulated the model cache")
	}
	saved, err = h.Plugins.ReadSource(source.SourceID)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = h.Plugins.Provider(context.Background(), saved); err != nil {
		t.Fatal(err)
	}
	var disk string
	_ = h.Ledger.db.QueryRow(`SELECT value FROM gateway_catalog WHERE id=1`).Scan(&disk)
	if strings.Contains(disk, "fixture-vendor-private") {
		t.Fatal("plugin credential leaked into catalog")
	}
}
