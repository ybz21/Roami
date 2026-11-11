package modelgateway

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/modelplugins"
)

func TestWorkBuddyPluginNonStreamClassifierUsesOneStreamedRequest(t *testing.T) {
	if os.Getenv("ROAMI_MAGPIE_BUN") == "" {
		t.Skip("set ROAMI_MAGPIE_BUN for the sandbox integration")
	}
	h := pluginTestHandler(t)
	script := `export const Plugin=async()=>({config:async cfg=>{cfg.provider??={};cfg.provider.workbuddy={name:'Stream-only fixture',npm:'@ai-sdk/openai-compatible',api:'https://fixture.invalid/v1',models:{sample:{name:'Configured model',id:'configured-upstream',limit:{context:1000,output:100}}}}},auth:{provider:'workbuddy',methods:[{type:'api',label:'Key'}],loader:async getAuth=>({apiKey:(await getAuth())?.key,fetch:async(url,init)=>{const body=JSON.parse(init.body);if(body.stream!==true)return new Response(JSON.stringify({code:11101,msg:'Non-stream chat request is currently not supported'}),{status:400});if(body.model!=='configured-upstream'||body.stream_options?.include_usage!==true)throw Error('route or usage changed');const events=[{choices:[{index:0,delta:{content:'{"decision":"allow"}'},finish_reason:'stop'}]},{choices:[],usage:{prompt_tokens:2,completion_tokens:3}}];return new Response(events.map(x=>'data: '+JSON.stringify(x)+'\n\n').join('')+'data: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}})}})}})`
	upload := pluginUpload(t, h, map[string]string{"package.json": `{"name":"stream-only-fixture","main":"index.mjs"}`, "index.mjs": script}, true)
	if upload.Code != 200 {
		t.Fatal(upload.Body)
	}
	var imported struct {
		Data modelplugins.Package `json:"data"`
	}
	if err := json.Unmarshal(upload.Body.Bytes(), &imported); err != nil {
		t.Fatal(err)
	}
	pluginJSON(t, h, "POST", "/inspect", map[string]any{"packageId": imported.Data.ID})
	created := pluginJSON(t, h, "POST", "/sources", map[string]any{"packageId": imported.Data.ID, "providerId": "workbuddy", "revision": h.Catalog.value.Revision})
	var source struct {
		SourceID string `json:"sourceId"`
	}
	if err := json.Unmarshal(created, &source); err != nil {
		t.Fatal(err)
	}
	pluginJSON(t, h, "POST", "/sources/"+source.SourceID+"/auth", map[string]any{"action": "apiKey", "method": 0, "key": "fixture-vendor-private"})
	next := h.Catalog.snapshot()
	next.Models = append(next.Models, CatalogModel{ID: "saved-alias", Name: "Saved alias", Protocol: "openai-completions", Strategy: "fixed", Candidates: []ModelCandidate{{SourceID: source.SourceID, Model: "sample"}}})
	if err := h.Catalog.update(context.Background(), next); err != nil {
		t.Fatal(err)
	}
	if w := setAccessKey(t, h, "PUT", "fixture-client-private", h.Catalog.value.Revision); w.Code != 200 {
		t.Fatal(w.Body)
	}
	response := requestWithKey(h, "fixture-client-private", "/v1/messages", `{"model":"saved-alias","max_tokens":32,"stream":false,"messages":[{"role":"user","content":"Classify a read-only command"}]}`)
	if response.Code != 200 || !strings.Contains(response.Header().Get("Content-Type"), "application/json") {
		t.Fatalf("classifier response: %d %s", response.Code, response.Body)
	}
	var result map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if result["model"] != "saved-alias" || objectValue(arrayValue(result["content"])[0])["text"] != `{"decision":"allow"}` {
		t.Fatalf("changed classifier output: %+v", result)
	}
	stats, err := h.Ledger.StatisticsForSource(1, "", "", "external")
	if err != nil || len(stats.Recent) != 1 || stats.Recent[0].SourceID != source.SourceID {
		t.Fatalf("request attribution changed: %+v %v", stats, err)
	}
}
