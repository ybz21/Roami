package modelgateway

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
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

func TestPluginImportEndpointDiscoversRepositoryCollection(t *testing.T) {
	h := pluginTestHandler(t)
	files := map[string]string{"package.json": `{"name":"workspace","workspaces":["packages/*"]}`, "packages/one/package.json": `{"name":"first-plugin","main":"index.mjs"}`, "packages/one/index.mjs": "export const Plugin=async()=>({})", "packages/two/package.json": `{"name":"second-plugin","main":"index.mjs"}`, "packages/two/index.mjs": "export const Plugin=async()=>({})", ".git/config": "not imported", ".env": "not imported"}
	for _, zipped := range []bool{false, true} {
		response := pluginUpload(t, h, files, zipped)
		if response.Code != 200 {
			t.Fatalf("collection %v: %d %s", zipped, response.Code, response.Body)
		}
		var result struct {
			Data modelplugins.Collection `json:"data"`
		}
		if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil || len(result.Data.Packages) != 2 {
			t.Fatalf("collection result: %s %v", response.Body, err)
		}
	}
}

func TestPluginFolderImportSupportsMoreThanDefaultMultipartPartLimit(t *testing.T) {
	h := pluginTestHandler(t)
	files := map[string]string{"package.json": `{"name":"plugin","main":"index.mjs"}`, "index.mjs": "export const Plugin=async()=>({})"}
	for i := 0; i < 510; i++ {
		files[fmt.Sprintf("docs/file-%d.txt", i)] = "documentation"
	}
	response := pluginUpload(t, h, files, false)
	if response.Code != 200 {
		t.Fatalf("multipart collection: %d %s", response.Code, response.Body)
	}
}

func TestPluginTenIndependentAccounts(t *testing.T) {
	if os.Getenv("ROAMI_MAGPIE_BUN") == "" {
		t.Skip("set ROAMI_MAGPIE_BUN for the sandbox integration")
	}
	h := pluginTestHandler(t)
	script := `export const Plugin=async()=>({config:async cfg=>{cfg.provider??={};cfg.provider.workbuddy={name:'WorkBuddy',npm:'@ai-sdk/openai-compatible',api:'https://fixture.invalid/v1',models:{sample:{name:'Sample',limit:{context:1000,output:100}}}}},auth:{provider:'workbuddy',methods:[{type:'api',label:'Key'}],loader:async getAuth=>({apiKey:(await getAuth())?.key,fetch:async()=>new Response(JSON.stringify({id:'fixture',choices:[{message:{role:'assistant',content:(await getAuth())?.key},finish_reason:'stop'}],usage:{prompt_tokens:2,completion_tokens:1}}),{headers:{'content-type':'application/json'}})})}})`
	uploaded := pluginUpload(t, h, map[string]string{"package.json": `{"name":"test-multi-workbuddy","main":"index.mjs"}`, "index.mjs": script}, true)
	if uploaded.Code != 200 {
		t.Fatal(uploaded.Body.String())
	}
	var pkg struct {
		Data modelplugins.Package `json:"data"`
	}
	if err := json.Unmarshal(uploaded.Body.Bytes(), &pkg); err != nil {
		t.Fatal(err)
	}
	ids := []string{}
	for i := 0; i < 10; i++ {
		input := map[string]any{"packageId": pkg.Data.ID, "providerId": "workbuddy", "revision": h.Catalog.value.Revision}
		if i > 0 {
			input = map[string]any{"sourceId": ids[0], "revision": h.Catalog.value.Revision}
		}
		raw := pluginJSON(t, h, "POST", "/sources", input)
		var created struct {
			SourceID string `json:"sourceId"`
		}
		if err := json.Unmarshal(raw, &created); err != nil {
			t.Fatal(err)
		}
		for _, id := range ids {
			if id == created.SourceID {
				t.Fatal("instance reused")
			}
		}
		ids = append(ids, created.SourceID)
		before := pluginJSON(t, h, "GET", "/sources/"+created.SourceID+"/info", nil)
		var info struct {
			Provider modelplugins.Provider `json:"provider"`
		}
		if err := json.Unmarshal(before, &info); err != nil || info.Provider.SignedIn {
			t.Fatal("new instance copied credentials", err)
		}
		pluginJSON(t, h, "POST", "/sources/"+created.SourceID+"/auth", map[string]any{"action": "apiKey", "method": 0, "key": fmt.Sprintf("fixture-%d", i)})
		source, err := h.Plugins.ReadSource(created.SourceID)
		if err != nil {
			t.Fatal(err)
		}
		if source.PackageID != pkg.Data.ID {
			t.Fatal("package was duplicated")
		}
		if err = h.Plugins.SetOptions(context.Background(), source, map[string]any{"fixtureFlag": i%2 == 0}); err != nil {
			t.Fatal(err)
		}
		source, _ = h.Plugins.ReadSource(created.SourceID)
		if _, err = h.Plugins.Provider(context.Background(), source); err != nil {
			t.Fatal(err)
		}
	}
	names := map[string]bool{}
	for _, row := range h.Catalog.value.Sources {
		if row.PluginSourceID != "" {
			if names[row.Name] {
				t.Fatal("duplicate account name")
			}
			names[row.Name] = true
		}
	}
	verify := func() {
		t.Helper()
		for i, id := range ids {
			source, err := h.Plugins.ReadSource(id)
			if err != nil {
				t.Fatal(err)
			}
			if source.Options["fixtureFlag"] != (i%2 == 0) {
				t.Fatal("options crossed accounts")
			}
			provider, err := h.Plugins.Provider(context.Background(), source)
			if err != nil {
				t.Fatal(err)
			}
			request := httptest.NewRequest("POST", "https://fixture.invalid/v1/chat/completions", strings.NewReader(`{}`))
			response, err := h.Plugins.Fetch(context.Background(), source, provider.Models[0], provider, request, []byte(`{}`))
			if err != nil {
				t.Fatal(err)
			}
			data, err := io.ReadAll(response.Body)
			_ = response.Body.Close()
			if err != nil || !strings.Contains(string(data), fmt.Sprintf(`"content":"fixture-%d"`, i)) {
				t.Fatalf("account %d routed with wrong credential: %v", i, err)
			}
		}
	}
	verify()
	results := make(chan error, len(ids))
	for index, id := range ids {
		go func(index int, id string) {
			source, err := h.Plugins.ReadSource(id)
			if err != nil {
				results <- err
				return
			}
			provider, err := h.Plugins.Provider(context.Background(), source)
			if err != nil {
				results <- err
				return
			}
			response, err := h.Plugins.Fetch(context.Background(), source, provider.Models[0], provider, httptest.NewRequest("POST", "https://fixture.invalid/v1/chat/completions", nil), []byte(`{}`))
			if err != nil {
				results <- err
				return
			}
			data, err := io.ReadAll(response.Body)
			_ = response.Body.Close()
			if err == nil && !strings.Contains(string(data), fmt.Sprintf(`"content":"fixture-%d"`, index)) {
				err = fmt.Errorf("concurrent account %d crossed credentials", index)
			}
			results <- err
		}(index, id)
	}
	for range ids {
		if err := <-results; err != nil {
			t.Fatal(err)
		}
	}
	root := h.Plugins.Root
	h.Plugins.Close()
	manager, err := modelplugins.NewManager(root)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(manager.Close)
	h.Plugins = manager
	h.Catalog.plugins = manager
	manager.AuthChanged = h.pluginAuthChanged
	verify()
	pluginJSON(t, h, "POST", "/sources/"+ids[0]+"/auth", map[string]any{"action": "signOut"})
	first, _ := manager.ReadSource(ids[0])
	p, err := manager.Provider(context.Background(), first)
	if err != nil || p.SignedIn {
		t.Fatal("first instance did not sign out", err)
	}
	second, _ := manager.ReadSource(ids[1])
	p, err = manager.Provider(context.Background(), second)
	if err != nil || !p.SignedIn {
		t.Fatal("sign-out affected another account", err)
	}
}
